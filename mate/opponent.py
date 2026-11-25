"""The local Stockfish worker. No network destination or engine runs inside PostgreSQL."""

import os
import shutil
from pathlib import Path

import chess
import chess.engine
from psycopg import Connection

from . import cluster
from .game import Game, get, moves, record, replay, wake


def open_engine() -> chess.engine.SimpleEngine:
    configured = os.environ.get("STOCKFISH")
    candidates = ([configured] if configured else
                  ["stockfish", "/usr/games/stockfish", str(cluster.STATE / "engine/usr/games/stockfish")])
    for candidate in candidates:
        path = shutil.which(candidate)
        if path:
            return chess.engine.SimpleEngine.popen_uci(str(Path(path).resolve()), timeout=5)
    raise ValueError("Stockfish not found. Install Stockfish or set STOCKFISH to its executable.")


def reply(db: Connection, engine: chess.engine.SimpleEngine, game: Game) -> bool:
    board = replay(game, moves(db, game))
    if game.phase != "engine" or board.turn != chess.BLACK:
        raise RuntimeError(f"Game {game.id} is not ready for a black reply")
    if engine.id["name"] != game.engine:
        raise ValueError(f"Game {game.id} needs {game.engine}; configured engine is {engine.id['name']}")
    result = engine.play(board, chess.engine.Limit(time=0.25, nodes=20_000), game=game.id)
    if result.move is None or result.move not in board.legal_moves:
        raise RuntimeError(f"{game.engine} returned no legal move for game {game.id}")
    with db.transaction():
        current = get(db, game.id, lock=True)
        # A search may repeat after a crash or in another worker; only one reply can commit.
        if current.phase != "engine" or current.ply != game.ply:
            return False
        record(db, current, board, result.move, None)
    return True


def advance(db: Connection, engine: chess.engine.SimpleEngine, game_id: int) -> None:
    game = get(db, game_id)
    if game.phase in ("submitted", "closing"):
        wake(db, game)
    elif game.phase == "engine":
        reply(db, engine, game)
