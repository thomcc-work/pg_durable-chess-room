import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import chess
import chess.engine

from chess_room import cluster, game, opponent
from chess_room.game_demo import wait_until
from chess_room.room import EngineWorker


class EngineReplacement(unittest.TestCase):
    def test_shared_process_recovers_two_committed_turns_without_duplicate_moves(self):
        cluster.use_private_socket()
        broken, replacement = Mock(), Mock()
        broken.id = replacement.id = {"name": "test engine"}
        broken.play.side_effect = chess.engine.EngineTerminatedError("engine exited")
        replacement.play.return_value = SimpleNamespace(move=chess.Move.from_uci("e7e5"))
        worker = EngineWorker(broken)
        with cluster.connect() as db:
            game.install(db)
            games = [game.create(db, "test engine", hold_engine=True) for _ in range(2)]
            for gid in games:
                game.submit(db, gid, 0, "e2e4", uuid4())
                wait_until(db, broken, gid, "engine")
                game.hold_engine(db, gid, False)
            with patch.object(opponent, "open_engine", side_effect=[OSError("not ready"), replacement]) as reopen:
                worker.advance_turn(db, games[0], "engine")
                worker.advance_turn(db, games[1], "engine")
                broken.close.assert_called_once()
                reopen.assert_not_called()
                worker.engine_retry_at = 0
                worker.advance_turn(db, games[0], "engine")
                self.assertEqual(worker.engine_delay, 4)
                worker.engine_retry_at = 0
                for gid in games * 2:
                    worker.advance_turn(db, gid, "engine")
                self.assertEqual(reopen.call_count, 2)
                self.assertIsNone(worker.engine_issue)
            for gid in games:
                g = game.get(db, gid)
                self.assertEqual(g.phase, "human")
                self.assertEqual([m.uci for m in game.moves(db, g)], ["e2e4", "e7e5"])
