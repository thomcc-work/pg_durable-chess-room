"""Freeze a comparison, submit durable cells, then grade their recorded replies."""

import csv
import json
import re
from dataclasses import dataclass
from itertools import groupby

import psycopg
from psycopg import Connection
from psycopg.rows import class_row
from psycopg.types.json import Jsonb

from .cluster import ROOT
from .evaluation import HINT, canned_reply, comparison, grade, prompt


@dataclass(frozen=True)
class Run:
    id: int
    provider: str
    deployment: str
    settings: dict
    base_url: str | None
    api_version: str | None


def get_run(db: Connection, run_id: int) -> Run:
    with db.cursor(row_factory=class_row(Run)) as cur:
        run = cur.execute("SELECT id, provider, deployment, settings, base_url, api_version "
                          "FROM chess_room.run WHERE id = %s", (run_id,)).fetchone()
    if run is None:
        raise ValueError(f"No such run: {run_id}")
    return run


def chat_base_url(db: Connection) -> str:
    row = db.execute("""
        SELECT o.option_value FROM pg_foreign_server s
        JOIN pg_foreign_data_wrapper w ON w.oid = s.srvfdw, pg_options_to_table(s.srvoptions) o
        WHERE s.srvname = 'chess_room_chat' AND w.fdwname = 'pg_durable_fdw' AND o.option_name = 'base_url'
    """).fetchone()
    if not row or not re.fullmatch(r"https://[A-Za-z0-9-]+\.openai\.azure\.com/?", row[0]):
        raise ValueError("Configure chess_room_chat with the HTTPS base URL of your authorized Azure resource.")
    return row[0]


def new_run(db: Connection, count: int | None, deployment: str | None = None) -> int:
    with (ROOT / "data/boards.csv").open(newline="", encoding="utf-8") as data:
        boards = list(csv.DictReader(data))
    count = len(boards) if count is None else count
    if not 1 <= count <= len(boards):
        raise ValueError(f"Choose 1..{len(boards)} boards")
    live = deployment is not None
    if live and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", deployment):
        raise ValueError("Invalid Azure deployment name")
    with db.transaction():
        run_id, = db.execute("""
            INSERT INTO chess_room.run(provider, deployment, settings, base_url, api_version)
            VALUES (%s,%s,%s,%s,%s) RETURNING id
        """, ("azure" if live else "fixture", deployment or "canned-v1",
              Jsonb({"temperature": 0, "max_tokens": 32, "n": 1}),
              chat_base_url(db) if live else None, "2024-10-21" if live else None)).fetchone()
        cells = []
        for row in boards[:count]:
            for variant in HINT:
                key = variant.lower()
                fixture = None if live else Jsonb(canned_reply(int(row[f"{key}_status"]), row[f"{key}_text"]))
                cells.append((run_id, int(row["board"]), row["title"], row["fen"], row["mates"].split(),
                              variant, prompt(variant, row["fen"]), fixture))
        with db.cursor() as cur:
            cur.executemany("INSERT INTO chess_room.cell(run_id,board,title,fen,mates,variant,prompt,fixture) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", cells)
    return run_id


def request_node(db: Connection, run: Run, cell_id: int, message: str) -> str:
    if run.provider == "fixture":
        # The insert is unconditional: replay must remain visible at the fixture provider.
        query = f"""WITH receipt AS (
            INSERT INTO chess_room.fixture_attempt(cell_id) VALUES ({cell_id}) RETURNING cell_id
        ) SELECT (fixture->>'status')::int AS status, 'text' AS encoding, fixture->>'body' AS body
          FROM chess_room.cell JOIN receipt ON id = cell_id"""
        return db.execute("SELECT df.sql(%s)", (query,)).fetchone()[0]
    if chat_base_url(db) != run.base_url:
        raise ValueError(f"chess_room_chat destination changed since run {run.id} was frozen")
    path = f"/openai/deployments/{run.deployment}/chat/completions?api-version={run.api_version}"
    body = run.settings | {"messages": [{"role": "user", "content": message}]}
    return db.execute("""
        SELECT df.http(df.endpoint('chess_room_chat', %s), 'POST', %s, '{"Content-Type":"application/json"}'::jsonb)
    """, (path, json.dumps(body))).fetchone()[0]


def launch_pair(db: Connection, run: Run, board: int, *, delay_request=False, delay_finish=False) -> None:
    with db.transaction():
        cells = db.execute("SELECT id, variant, prompt FROM chess_room.cell WHERE run_id=%s AND board=%s "
                           "AND instance IS NULL ORDER BY variant FOR UPDATE", (run.id, board)).fetchall()
        for cell_id, variant, message in cells:
            request = request_node(db, run, cell_id, message)
            capture = (f"UPDATE chess_room.cell SET http_status=$reply.status, encoding=$reply.encoding, "
                       f"body=$reply.body WHERE id={cell_id}")
            graph, = db.execute("SELECT (%s::text |=> 'reply') ~> df.sql(%s)", (request, capture)).fetchone()
            if delay_request:
                graph, = db.execute("SELECT df.sleep(15) ~> %s::text", (graph,)).fetchone()
            if delay_finish:
                graph, = db.execute("SELECT %s::text ~> df.sleep(15)", (graph,)).fetchone()
            db.execute("UPDATE chess_room.cell SET instance=df.start(%s,%s) WHERE id=%s",
                       (graph, f"chess-room/eval/{run.id}/{board}/{variant}", cell_id))


def workflow_failure(db: Connection, cell_id: int, instance: str) -> str | None:
    info = db.execute("SELECT status, output FROM df.instance_info(%s)", (instance,)).fetchone()
    if info and info[0] in ("failed", "cancelled"):
        reason = info[1] or info[0]
    elif not info and not db.execute("SELECT 1 FROM df.instances WHERE instance_id=%s", (instance,)).fetchone():
        reason = "Workflow history expired without a recorded response"
    else:
        return None
    stored = db.execute("UPDATE chess_room.cell SET verdict='workflow_error', workflow_error=%s "
                        "WHERE id=%s AND verdict IS NULL AND http_status IS NULL RETURNING workflow_error",
                        (reason, cell_id)).fetchone()
    return stored[0] if stored else None


def finish_pair(db: Connection, run: Run, board: int) -> None:
    launch_pair(db, run, board)
    cells = db.execute("SELECT id, instance, http_status FROM chess_room.cell "
                       "WHERE run_id=%s AND board=%s AND verdict IS NULL",
                       (run.id, board)).fetchall()
    for cell_id, instance, captured in cells:
        if captured is None:
            if workflow_failure(db, cell_id, instance):
                continue
            try:
                state, = db.execute("SELECT df.await_instance(%s, 90)", (instance,)).fetchone()
            except psycopg.DatabaseError:
                # Pruning can race the wait. Don't mask other failures or reissue the request.
                if db.execute("SELECT 1 FROM df.instances WHERE instance_id=%s", (instance,)).fetchone():
                    raise
                state = "expired"
            if state not in ("completed", "failed", "cancelled", "expired"):
                raise ValueError(f"Workflow {instance} is not terminal: {state}")
        # Read in a fresh statement: the worker may have committed its reply while we waited.
        status, encoding, body, mates = db.execute(
            "SELECT http_status, encoding, body, mates FROM chess_room.cell WHERE id=%s", (cell_id,)
        ).fetchone()
        if status is None:
            if workflow_failure(db, cell_id, instance):
                continue
            raise ValueError(f"Workflow {instance} completed without recording a response")
        verdict, answer = grade(status, encoding, body, mates)
        db.execute("UPDATE chess_room.cell SET verdict=%s, answer=%s WHERE id=%s AND verdict IS NULL",
                   (verdict, answer, cell_id))


def board_numbers(db: Connection, run: Run) -> list[int]:
    return [n for n, in db.execute("SELECT DISTINCT board FROM chess_room.cell WHERE run_id=%s ORDER BY board", (run.id,))]


def scorecard(db: Connection, run: Run) -> None:
    print(f"Run {run.id} | {run.provider} | {run.deployment} | {json.dumps(run.settings)}")
    cells = db.execute("SELECT board, title, variant, answer, verdict, http_status, instance, id, workflow_error "
                       "FROM chess_room.cell WHERE run_id=%s ORDER BY board, variant", (run.id,)).fetchall()
    table = [("Board", "Position", "A answer", "A verdict", "B answer", "B verdict", "Comparison")]
    for (board, title), pair in groupby(cells, key=lambda c: c[:2]):
        states, columns = {}, []
        for _, _, variant, answer, verdict, status, instance, cell_id, reason in pair:
            state = verdict or ("recorded" if status is not None else "pending")
            label = f"HTTP {status}" if state == "provider_error" else state
            if not verdict and status is None and instance:
                reason = workflow_failure(db, cell_id, instance)
            if reason:
                state, label = "workflow_error", f"workflow_error: {reason}"
            states[variant] = state
            columns.extend(("-" if answer is None else json.dumps(answer, ensure_ascii=False)[1:-1], label))
        table.append((str(board), title, *columns, comparison(states["A"], states["B"])))
    widths = [max(map(len, column)) for column in zip(*table, strict=True)]
    for row in table:
        print("  ".join(value.ljust(width) for value, width in zip(row, widths)).rstrip())


def finish(db: Connection, run: Run) -> None:
    for board in board_numbers(db, run):
        finish_pair(db, run, board)
    scorecard(db, run)
