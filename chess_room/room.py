"""Loopback-only board and its single local engine worker."""

import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import chess
import chess.pgn
import chess.svg
import psycopg

from . import cluster, game, opponent

ASSETS = Path(__file__).parent / "static"
COLORS = {"square light": "#eddcba", "square dark": "#719383",
          "square light lastmove": "#efcf81", "square dark lastmove": "#b7ad6f"}


def snapshot(db, g: game.Game, issue: str | None) -> dict:
    board = chess.Board(g.start_fen)
    history = []
    for p in game.moves(db, g):
        board.push_uci(p.uci)
        history.append({"ply": p.ply, "uci": p.uci, "san": p.san, "fen": board.fen(),
                        "request": str(p.request_id) if p.request_id else None})
    return {"id": g.id, "title": g.title, "engine": g.engine, "instance": g.instance,
            "phase": g.phase, "held": g.engine_paused, "result": g.result, "reason": g.reason, "ply": g.ply,
            "fen": g.fen, "start": g.start_fen, "moves": history, "check": board.is_check(),
            "legal": [m.uci() for m in board.legal_moves] if g.phase == "human" else [], "issue": issue}


def board_svg(board: chess.Board) -> str:
    return chess.svg.board(board, lastmove=board.peek() if board.move_stack else None,
                           check=board.king(board.turn) if board.is_check() else None,
                           coordinates=False, colors=COLORS)


def pgn(db, g: game.Game) -> str:
    record = chess.pgn.Game.from_board(game.replay(g, game.moves(db, g)))
    created, = db.execute("SELECT created_at FROM chess_room.game WHERE id=%s", (g.id,)).fetchone()
    record.headers.update(Event=f"The Chess Room / Game {g.id}", Site="Local board", Date=created.strftime("%Y.%m.%d"),
                          White="Human", Black=g.engine, Result=g.result)
    return str(record) + "\n"


class EngineWorker(threading.Thread):
    def __init__(self, engine):
        super().__init__(name="stockfish-worker", daemon=True)
        self.engine = engine
        self.stop_event = threading.Event()
        self.issues: dict[int, str] = {}

    def run(self):
        offline = False
        retry_at: dict[int, tuple[str, float]] = {}
        while not self.stop_event.is_set():
            try:
                with cluster.connect() as db:
                    if offline:
                        print("Game worker reconnected.", file=sys.stderr)
                    offline = False
                    while not self.stop_event.is_set():
                        pending = db.execute("SELECT id,phase FROM chess_room.game WHERE phase IN ('submitted','closing') "
                                             "OR (phase='engine' AND NOT engine_paused) ORDER BY id").fetchall()
                        for gid, phase in pending:
                            failed_phase, retry = retry_at.get(gid, ("", 0))
                            if failed_phase == phase and time.monotonic() < retry:
                                continue
                            try:
                                opponent.advance(db, self.engine, gid)
                            except (psycopg.OperationalError, psycopg.InterfaceError):
                                raise
                            except psycopg.DatabaseError as exc:
                                # Postgres can accept SQL before the durable runtime is ready again.
                                retry_at[gid] = (phase, time.monotonic() + 5)
                                self.issues[gid] = f"Database step will retry: {exc}"
                                print(f"Game {gid}: {exc}", file=sys.stderr)
                            except (ValueError, RuntimeError, OSError, chess.engine.EngineError) as exc:
                                retry_at[gid] = (phase, float("inf"))
                                self.issues[gid] = f"Game worker paused: {exc}. Restart the room after correcting it."
                                print(f"Game {gid}: {exc}", file=sys.stderr)
                            else:
                                self.issues.pop(gid, None)
                                retry_at.pop(gid, None)
                        self.stop_event.wait(0.3 if pending else 0.6)
            except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
                if not offline:
                    print(f"Game worker waiting for Postgres: {exc}", file=sys.stderr)
                offline = True
                self.stop_event.wait(0.6)


class BoardServer(ThreadingHTTPServer):
    def __init__(self, port, worker):
        super().__init__(("127.0.0.1", port), BoardHandler)
        self.worker = worker
        self.opponent_name = worker.engine.id["name"]


class BoardHandler(BaseHTTPRequestHandler):
    server: BoardServer

    def respond(self, status, body, mime="application/json", *, attachment=None):
        data = (json.dumps(body) if mime == "application/json" else body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; frame-ancestors 'none'")
        if attachment:
            self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
        self.end_headers()
        self.wfile.write(data)

    def dispatch(self, post=False):
        host = self.headers.get("Host")
        port = self.server.server_port
        if port == 80 and host in ("localhost", "127.0.0.1"):
            host += ":80"
        if host not in (f"localhost:{port}", f"127.0.0.1:{port}"):
            self.respond(403, {"error": "Use the local board address printed at startup"})
            return
        target = urlsplit(self.path)
        try:
            if post:
                origins = {None, f"http://{host}"}
                if port == 80:
                    origins.add("http://" + host.removesuffix(":80"))
                if self.headers.get("Origin") not in origins:
                    self.respond(403, {"error": "Use the same-origin board"})
                    return
                size = int(self.headers.get("Content-Length", "0"))
                if self.headers.get_content_type() != "application/json" or not 0 < size <= 2048:
                    self.respond(400, {"error": "Expected a small JSON object"})
                    return
                body = json.loads(self.rfile.read(size).decode("utf-8"))
                if not isinstance(body, dict):
                    raise ValueError("Expected a JSON object")
                self.mutate(target.path, body)
            else:
                self.read(target)
        except game.NoGame as exc:
            self.respond(404, {"error": str(exc)})
        except game.MoveConflict as exc:
            self.respond(409, {"error": str(exc)})
        except (ValueError, OverflowError, RecursionError) as exc:
            self.respond(400, {"error": str(exc)})
        except (psycopg.OperationalError, psycopg.InterfaceError):
            self.respond(503, {"error": "Postgres is offline. Your saved game will reconnect."})
        except psycopg.DatabaseError as exc:
            self.log_error("Database error: %s", exc)
            self.respond(500, {"error": "Database operation failed. See the board server log."})

    def read(self, target):
        files = {"/": ("index.html", "text/html"), "/room.css": ("room.css", "text/css"),
                 "/room.js": ("room.js", "text/javascript")}
        path = target.path
        if re.fullmatch(r"/games/[1-9][0-9]*", path):
            path = "/"
        if path in files:
            name, mime = files[path]
            self.respond(200, (ASSETS / name).read_text(), mime)
            return
        if path == "/opening.svg":
            self.respond(200, board_svg(chess.Board()), "image/svg+xml")
            return
        if path == "/knight.svg":
            self.respond(200, chess.svg.piece(chess.Piece(chess.KNIGHT, chess.BLACK)), "image/svg+xml")
            return
        with cluster.connect() as db:
            if path == "/api/games":
                games = db.execute("SELECT id,title,ply,result FROM chess_room.game ORDER BY id DESC LIMIT 50").fetchall()
                self.respond(200, {"games": [{"id": i, "title": t, "ply": p, "result": r} for i, t, p, r in games],
                                   "engine": self.server.opponent_name})
                return
            match = re.fullmatch(r"/api/games/([1-9][0-9]{0,17})(/board\.svg|/score\.pgn)?", path)
            if not match:
                self.respond(404, {"error": "Not found"})
                return
            g = game.get(db, int(match[1]))
            if match[2] == "/score.pgn":
                self.respond(200, pgn(db, g), "application/x-chess-pgn", attachment=f"game-{g.id}.pgn")
            elif match[2] == "/board.svg":
                ply = int(parse_qs(target.query).get("ply", [g.ply])[0])
                if not 0 <= ply <= g.ply:
                    raise ValueError("Unknown ply")
                board = chess.Board(g.start_fen)
                for move in game.moves(db, g)[:ply]:
                    board.push_uci(move.uci)
                self.respond(200, board_svg(board), "image/svg+xml")
            else:
                self.respond(200, snapshot(db, g, self.server.worker.issues.get(g.id)))

    def mutate(self, path, body):
        with cluster.connect() as db:
            if path == "/api/games":
                preset = body.get("preset", "standard")
                if not isinstance(preset, str):
                    raise ValueError("Expected a starting position name")
                self.respond(201, {"id": game.create(db, self.server.opponent_name, preset)})
                return
            match = re.fullmatch(r"/api/games/([1-9][0-9]{0,17})/(move|resign|hold)", path)
            if not match:
                self.respond(404, {"error": "Not found"})
                return
            gid, ply = int(match[1]), body.get("ply")
            if match[2] == "hold":
                paused = body.get("paused")
                if type(paused) is not bool:
                    raise ValueError("Expected a boolean paused setting")
                game.hold_engine(db, gid, paused)
                self.respond(200, {"held": paused})
                return
            if type(ply) is not int or not 0 <= ply < 2**31:
                raise ValueError("Expected a non-negative ply number")
            if match[2] == "resign":
                game.resign(db, gid, ply)
                self.respond(200, {"resigned": True})
                return
            uci, key = body.get("uci"), body.get("request")
            if not isinstance(uci, str) or not isinstance(key, str):
                raise ValueError("Expected a UCI move and a request UUID")
            request_id = UUID(key)
            applied = game.submit(db, gid, ply, uci, request_id)
            self.respond(200, {"applied": applied, "receipt": {"request": str(request_id), "ply": ply + 1, "uci": uci}})

    def do_GET(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch(post=True)

    def log_request(self, code="-", size="-"):
        if str(code).startswith(("4", "5")):
            super().log_request(code, size)


def serve(port: int) -> None:
    if not 0 <= port <= 65535:
        raise ValueError("Port must be in 0..65535")
    with cluster.connect() as db:
        game.install(db)
    with opponent.open_engine() as engine:
        worker = EngineWorker(engine)
        with BoardServer(port, worker) as server:
            worker.start()
            print(f"The Chess Room / {engine.id['name']}: http://127.0.0.1:{server.server_port}", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                worker.stop_event.set()
                worker.join()
