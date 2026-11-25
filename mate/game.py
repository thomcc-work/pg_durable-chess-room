"""A human plays White. Python owns chess; one pg_durable loop releases each engine turn."""

import csv
from dataclasses import dataclass
from uuid import UUID

import chess
from psycopg import Connection
from psycopg.rows import class_row

from .cluster import ROOT


class NoGame(ValueError):
    pass


class MoveConflict(ValueError):
    pass


@dataclass(frozen=True)
class Game:
    id: int
    instance: str
    title: str
    engine: str
    start_fen: str
    fen: str
    ply: int
    phase: str
    result: str
    reason: str | None


@dataclass(frozen=True)
class Ply:
    ply: int
    actor: str
    uci: str
    san: str
    request_id: UUID | None


def install(db: Connection) -> None:
    # Also upgrades a retained evaluator database, without touching its tables.
    with db.transaction():
        db.execute("SELECT pg_advisory_xact_lock(17422, 1)")
        if db.execute("SELECT to_regclass('mate.game_move')").fetchone() == (None,):
            db.execute((ROOT / "sql/game.sql").read_text())


def presets() -> dict[str, tuple[str, str]]:
    result = {"standard": ("Starting position", chess.STARTING_FEN)}
    with (ROOT / "data/boards.csv").open(newline="") as source:
        for row in csv.DictReader(source):
            if row["board"] in ("1", "5"):
                result["puzzle-" + row["board"]] = (row["title"], row["fen"])
    return result


def create(db: Connection, engine: str, preset: str = "standard") -> int:
    try:
        title, fen = presets()[preset]
    except KeyError:
        raise ValueError("Unknown starting position") from None
    with db.transaction():
        game_id, = db.execute("INSERT INTO mate.game(title,engine,start_fen,fen) VALUES (%s,%s,%s,%s) "
                              "RETURNING id", (title, engine, fen, fen)).fetchone()
        release = (f"UPDATE mate.game SET phase=CASE phase WHEN 'submitted' THEN 'engine' "
                   f"ELSE 'finished' END WHERE id={game_id} AND phase IN ('submitted','closing')")
        ongoing = f"SELECT phase <> 'finished' FROM mate.game WHERE id={game_id}"
        db.execute("""UPDATE mate.game SET instance=df.start(df.loop(
                        df.wait_for_signal('turn') ~> df.sql(%s), df.sql(%s)), %s) WHERE id=%s""",
                   (release, ongoing, f"chess/{game_id}", game_id))
    return game_id


def get(db: Connection, game_id: int, *, lock: bool = False) -> Game:
    with db.cursor(row_factory=class_row(Game)) as cur:
        game = cur.execute("SELECT id,instance,title,engine,start_fen,fen,ply,phase,result,reason "
                           "FROM mate.game WHERE id=%s" + (" FOR UPDATE" if lock else ""), (game_id,)).fetchone()
    if game is None:
        raise NoGame(f"No game {game_id}")
    return game


def moves(db: Connection, game: Game) -> list[Ply]:
    with db.cursor(row_factory=class_row(Ply)) as cur:
        return cur.execute("SELECT ply,actor,uci,san,request_id FROM mate.game_move WHERE game_id=%s "
                           "AND ply<=%s ORDER BY ply", (game.id, game.ply)).fetchall()


def replay(game: Game, history: list[Ply]) -> chess.Board:
    board = chess.Board(game.start_fen)
    for move in history:
        board.push_uci(move.uci)
    if len(history) != game.ply or board.fen() != game.fen:
        raise RuntimeError(f"Move history and saved position disagree in game {game.id}")
    return board


def record(db: Connection, game: Game, board: chess.Board, move: chess.Move, request: UUID | None) -> None:
    san = board.san(move)
    board.push(move)
    outcome = board.outcome()  # Automatic draws only: keep the real move stack for fivefold repetition.
    phase = "closing" if outcome else ("submitted" if request else "human")
    db.execute("INSERT INTO mate.game_move(game_id,ply,actor,uci,san,request_id) VALUES (%s,%s,%s,%s,%s,%s)",
               (game.id, game.ply + 1, "human" if request else "engine", move.uci(), san, request))
    db.execute("UPDATE mate.game SET ply=ply+1, fen=%s, phase=%s, result=%s, reason=%s WHERE id=%s",
               (board.fen(), phase, outcome.result() if outcome else "*",
                outcome.termination.name.lower().replace("_", " ") if outcome else None, game.id))


def submit(db: Connection, game_id: int, expected_ply: int, uci: str, request: UUID) -> bool:
    """Return False for an exact retry, including after subsequent turns."""
    with db.transaction():
        game = get(db, game_id, lock=True)
        old = db.execute("SELECT ply,uci FROM mate.game_move WHERE game_id=%s AND request_id=%s",
                         (game_id, request)).fetchone()
        if old is not None:
            if old != (expected_ply + 1, uci):
                raise MoveConflict("This request ID already belongs to a different move")
            return False
        if game.ply != expected_ply or game.phase != "human":
            raise MoveConflict("The board has changed or it is not White's turn")
        board = replay(game, moves(db, game))
        move = chess.Move.from_uci(uci)
        if board.turn != chess.WHITE or move not in board.legal_moves:
            raise ValueError(f"Illegal move: {uci}")
        record(db, game, board, move, request)
    return True


def wake(db: Connection, game: Game) -> None:
    # A signal can arrive before the subscription exists. The committed phase,
    # not the signal payload, is the work; the worker nudges again until it changes.
    state, = db.execute("SELECT df.status(%s)", (game.instance,)).fetchone()
    if state in ("failed", "cancelled", "completed"):
        reason = db.execute("SELECT output FROM df.instance_info(%s)", (game.instance,)).fetchone()
        raise RuntimeError(f"Game {game.id}: workflow {game.instance} is {state}: {reason}")
    db.execute("SELECT df.signal(%s, 'turn')", (game.instance,))
