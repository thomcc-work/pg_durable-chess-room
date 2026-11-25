"""Repeatable recovery test with a real human command and a real Stockfish reply."""

import time
from uuid import uuid4

import chess

from . import cluster, game, opponent


def wait_until(db, engine, game_id: int, phase: str) -> game.Game:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        current = game.get(db, game_id)
        if current.phase == phase:
            return current
        opponent.advance(db, engine, game_id)
        time.sleep(0.15)
    raise TimeoutError(f"Game {game_id} did not reach {phase}; last phase: {current.phase}")


def demo() -> None:
    with opponent.open_engine() as engine:
        with cluster.connect() as db:
            game.install(db)
            game_id = game.create(db, engine.id["name"], hold_engine=True)
            key = uuid4()
            if not game.submit(db, game_id, 0, "e2e4", key):
                raise RuntimeError("Fresh request unexpectedly classified as a retry")
            before = wait_until(db, engine, game_id, "engine")
            history = game.moves(db, before)
            old_start, = db.execute("SELECT pg_postmaster_start_time()").fetchone()
            print(f"Game {game_id} | {before.engine} | workflow {before.instance}\n"
                  f"1. e4 recorded (request {key}); engine turn released.\n{before.fen}", flush=True)
        cluster.pg_ctl("restart")
        cluster.wait_for_worker()
        with cluster.connect() as db:
            restored = game.get(db, game_id)
            new_start, = db.execute("SELECT pg_postmaster_start_time()").fetchone()
            if new_start <= old_start or restored != before or game.moves(db, restored) != history:
                raise RuntimeError("Game, position or move receipts did not survive restart unchanged")
            if game.submit(db, game_id, 0, "e2e4", key):
                raise RuntimeError("Retry of 1. e4 was applied twice")
            game.hold_engine(db, game_id, False)
            current = wait_until(db, engine, game_id, "human")
            if current.ply != 2 or game.submit(db, game_id, 0, "e2e4", key):
                raise RuntimeError("Expected one White move and one engine reply")
            board = chess.Board(current.fen)
            knight = chess.Move.from_uci("g1f3")
            second = knight if knight in board.legal_moves else next(iter(board.legal_moves))
            game.submit(db, game_id, 2, second.uci(), uuid4())
            final = wait_until(db, engine, game_id, "human")
            line = game.moves(db, final)
            game.replay(final, line)
            if [m.actor for m in line] != ["human", "engine", "human", "engine"] or final.instance != before.instance:
                raise RuntimeError("Expected two full turns in the original workflow")
            print(f"Same FEN after restart; both retries recognized the recorded move.\n"
                  f"1. {line[0].san} {line[1].san} 2. {line[2].san} {line[3].san}\n"
                  f"Game {game_id} is ready for White on ply {final.ply}; workflow {final.instance}.")
