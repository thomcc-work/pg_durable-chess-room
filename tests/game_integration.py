"""Opt-in: run against the applet-owned cluster. Creates games, never calls a cloud."""

import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from mate import cluster, game


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
