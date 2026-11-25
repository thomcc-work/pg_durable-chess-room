"""Observe the fixture provider on both sides of an actual applet-cluster restart."""

import time

from psycopg import Connection

from . import cluster
from .experiment import board_numbers, finish, finish_pair, get_run, launch_pair, new_run, scorecard


def early_attempts(db: Connection, run_id: int, mid: int) -> list[tuple]:
    return db.execute("""
        SELECT c.board, c.variant, c.instance, a.attempt, c.http_status, md5(c.body)
        FROM mate.cell c JOIN mate.fixture_attempt a ON a.cell_id=c.id
        WHERE c.run_id=%s AND c.board<=%s ORDER BY board, variant, attempt
    """, (run_id, mid)).fetchall()


def demo(count: int | None) -> None:
    if count is not None and count < 2:
        raise ValueError("The restart demo needs at least two boards")
    with cluster.connect() as db:
        run = get_run(db, new_run(db, count))
        boards = board_numbers(db, run)
        cut = len(boards) // 2
        mid, following = boards[cut-1:cut+1]
        print(f"Fixture run {run.id}: interrupting between boards {mid} and {following}", flush=True)
        for board in boards[:cut-1]:
            finish_pair(db, run, board)
        launch_pair(db, run, mid, delay_finish=True)
        launch_pair(db, run, following, delay_request=True)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            waiting, = db.execute("""
                SELECT count(*) FROM mate.cell c, df.instance_nodes(c.instance) n
                WHERE c.run_id=%s AND c.board IN (%s,%s)
                AND n.node_type='SLEEP' AND n.inferred_status='running'
            """, (run.id, mid, following)).fetchone()
            if waiting == 4:
                break
            time.sleep(0.2)
        else:
            raise TimeoutError("Did not observe both pairs at their durable timers; not restarting")
        recorded, = db.execute("SELECT count(body) FROM mate.cell WHERE run_id=%s", (run.id,)).fetchone()
        if recorded != 2 * cut:
            raise ValueError(f"Missed restart window: {recorded} recorded responses")
        before = early_attempts(db, run.id, mid)
        scorecard(db, run)
        print("board|prompt|instance|fixture attempt|HTTP status|body MD5")
        for receipt in before:
            print(*receipt, sep="|")
        print(f"Restarting with {recorded} recorded responses.", flush=True)

    cluster.pg_ctl("restart")
    cluster.wait_for_worker()
    with cluster.connect() as db:
        finish(db, run)
        if before != early_attempts(db, run.id, mid):
            raise ValueError("Recorded cells changed instance, response or request history")
        receipts = db.execute("""
            SELECT c.id, c.board, c.verdict, df.status(c.instance), a.attempt,
                   a.received_at >= pg_postmaster_start_time()
            FROM mate.cell c LEFT JOIN mate.fixture_attempt a ON a.cell_id=c.id WHERE c.run_id=%s
        """, (run.id,)).fetchall()
        if (len(receipts) != 2 * len(boards) or len({r[0] for r in receipts}) != len(receipts)
                or any(not verdict or state != "completed" or attempt is None or (board > mid and not later)
                       for _, board, verdict, state, attempt, later in receipts)):
            raise ValueError("Expected one fixture invocation per graded cell, with later requests after restart")
        print(f"Run {run.id}: {len(receipts)} cells graded. The {len(before)} earlier request histories "
              f"are unchanged; all {len(receipts)-len(before)} remaining requests arrived after restart.")
