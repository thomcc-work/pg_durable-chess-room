"""Opt-in: run against the applet-owned cluster. Creates games, never calls a cloud."""

import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import chess

from chess_room import cluster, game, opponent
from chess_room.game_demo import wait_until


class DurableTurns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cluster.use_private_socket()
        with cluster.connect() as db:
            game.install(db)

    def test_racing_duplicate_mate_commits_once_and_completes_one_workflow(self):
        with cluster.connect() as db:
            gid = game.create(db, "unused: mate in one", "puzzle-1")
        barrier, key = threading.Barrier(2), uuid4()

        def send():
            with cluster.connect() as db:
                barrier.wait(timeout=5)
                return game.submit(db, gid, 0, "a2h2", key)

        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(send) for _ in range(2)]
            self.assertEqual(sorted(f.result() for f in futures), [False, True])
        with cluster.connect() as db:
            deadline = time.monotonic() + 15
            while (g := game.get(db, gid)).phase == "closing" and time.monotonic() < deadline:
                game.wake(db, g)
                time.sleep(0.1)
            self.assertEqual((g.ply, g.phase, g.result, g.reason), (1, "finished", "1-0", "checkmate"))
            self.assertEqual(db.execute("SELECT df.await_instance(%s, 10)", (g.instance,)).fetchone(), ("completed",))
            self.assertEqual([m.san for m in game.moves(db, g)], ["Rh2#"])
            self.assertFalse(game.submit(db, gid, 0, "a2h2", key))
            with self.assertRaises(game.MoveConflict):
                game.submit(db, gid, 0, "a2a8", key)
            with self.assertRaises(game.MoveConflict):
                game.submit(db, gid, 0, "a2h2", uuid4())

    def test_illegal_move_changes_nothing_and_underpromotion_is_legal(self):
        with cluster.connect() as db:
            gid = game.create(db, "unused: promotion", "puzzle-5")
            before = game.get(db, gid)
            with self.assertRaises(ValueError):
                game.submit(db, gid, 0, "c7c8", uuid4())
            self.assertEqual(game.get(db, gid), before)
            self.assertEqual(game.moves(db, before), [])
            self.assertTrue(game.submit(db, gid, 0, "c7c8r", uuid4()))
            g = game.get(db, gid)
            self.assertEqual((g.result, g.reason), ("1-0", "checkmate"))
            self.assertTrue(game.replay(g, game.moves(db, g)).is_checkmate())

    def test_restored_history_adjudicates_fivefold_repetition(self):
        # Script both knights to revisit the opening position. FEN alone cannot count repetitions.
        def knight_reply(board, limit, game):
            uci = "g8f6" if board.piece_at(chess.G8) else "f6g8"
            return SimpleNamespace(move=chess.Move.from_uci(uci))

        engine = SimpleNamespace(id={"name": "scripted knights"}, play=knight_reply)
        with cluster.connect() as db:
            gid = game.create(db, engine.id["name"])
            for i in range(8):
                game.submit(db, gid, 2*i, "g1f3" if i % 2 == 0 else "f3g1", uuid4())
                wait_until(db, engine, gid, "finished" if i == 7 else "human")
            g = game.get(db, gid)
            self.assertEqual((g.ply, g.result, g.reason), (16, "1/2-1/2", "fivefold repetition"))
            self.assertEqual(db.execute("SELECT df.await_instance(%s,10)", (g.instance,)).fetchone(), ("completed",))

    def test_search_cannot_resurrect_a_resigned_game(self):
        with cluster.connect() as db:
            gid = game.create(db, "scripted reply", hold_engine=True)
            game.submit(db, gid, 0, "e2e4", uuid4())
            # A second tab resigns after search starts but before the reply is recorded.
            def resign_during_search(board, limit, **kwargs):
                with cluster.connect() as other:
                    game.resign(other, gid, 1)
                return SimpleNamespace(move=chess.Move.from_uci("e7e5"))

            engine = SimpleNamespace(id={"name": "scripted reply"}, play=resign_during_search)
            wait_until(db, engine, gid, "engine")
            game.hold_engine(db, gid, False)
            self.assertFalse(opponent.reply(db, engine, game.get(db, gid)))
            final = wait_until(db, engine, gid, "finished")
            self.assertEqual((final.ply, final.result, final.reason), (1, "0-1", "resignation"))
