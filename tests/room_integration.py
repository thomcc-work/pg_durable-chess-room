"""Exercise the local HTTP contract, using a mating position that needs no engine reply."""

import io
import json
import threading
import unittest
import urllib.error
import urllib.request
from types import SimpleNamespace
from uuid import uuid4

import chess.pgn

from mate import cluster, game
from mate.room import BoardServer


class BoardHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cluster.use_private_socket()
        with cluster.connect() as db:
            game.install(db)
        cls.server = BoardServer(0, SimpleNamespace(engine=SimpleNamespace(id={"name": "unused: terminal test"}), issues={}))
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join()
        cls.server.server_close()

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as res:
            return json.load(res)

    def test_move_receipt_pgn_and_historical_board(self):
        gid = self.post("/api/games", {"preset": "puzzle-5"})["id"]
        path = f"/api/games/{gid}"
        command = {"ply": 0, "uci": "c7c8r", "request": str(uuid4())}
        first = self.post(path + "/move", command)
        duplicate = self.post(path + "/move", command)
        self.assertTrue(first["applied"])
        self.assertFalse(duplicate["applied"])
        self.assertEqual(first["receipt"], duplicate["receipt"])
        with self.assertRaises(urllib.error.HTTPError) as conflict:
            self.post(path + "/move", command | {"uci": "c7c8q"})
        self.assertEqual(conflict.exception.code, 409)
        with urllib.request.urlopen(self.base + path) as response:
            snapshot = json.load(response)
        self.assertEqual((snapshot["ply"], snapshot["result"], snapshot["moves"][0]["san"]), (1, "1-0", "c8=R#"))
        with urllib.request.urlopen(self.base + path + "/score.pgn") as response:
            record = chess.pgn.read_game(io.StringIO(response.read().decode()))
        self.assertEqual(record.headers["Result"], "1-0")
        self.assertEqual(record.end().board().fen(), snapshot["fen"])
        images = []
        for ply in (0, 1):
            with urllib.request.urlopen(f"{self.base}{path}/board.svg?ply={ply}") as response:
                self.assertEqual(response.headers.get_content_type(), "image/svg+xml")
                images.append(response.read())
        self.assertNotEqual(*images)
