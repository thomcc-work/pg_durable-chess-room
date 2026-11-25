# /// script
# dependencies = ["chess==1.11.2"]
# ///
"""Recompute the entire mate-in-one answer key with python-chess, offline."""

import csv
from pathlib import Path

import chess


def mating_moves(fen):
    board = chess.Board(fen)
    if not board.is_valid():
        raise ValueError(f"Invalid position: {fen}")
    moves = []
    for move in list(board.legal_moves):
        board.push(move)
        if board.is_checkmate():
            moves.append(move.uci())
        board.pop()
    return sorted(moves)


if __name__ == "__main__":
    path = Path(__file__).resolve().parents[1] / "data/boards.csv"
    with path.open(newline="", encoding="utf-8") as data:
        for number, row in enumerate(csv.DictReader(data), 1):
            moves = mating_moves(row["fen"])
            print(f'{number:2} {row["title"]}: {" ".join(moves)}')
            if int(row["board"]) != number or not moves or moves != row["mates"].split():
                raise SystemExit(f"Board number or accepted moves disagree on row {number}")
