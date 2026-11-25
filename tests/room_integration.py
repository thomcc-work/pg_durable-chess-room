"""Exercise the local HTTP contract, using a mating position that needs no engine reply."""

import io
import http.client
import json
import threading
import unittest
import urllib.error
import urllib.request
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch

import chess.pgn

from chess_room import cluster, game
from chess_room.room import BoardServer


class BoardHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cluster.use_private_socket()
        with cluster.connect() as db:
            game.install(db)
        cls.server = BoardServer(0, SimpleNamespace(engine=SimpleNamespace(id={"name": "unused: terminal test"}),
                                                    issues={}, engine_issue=None))
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

    def test_default_port_host_and_same_origin(self):
        # Exercise ordinary port-80 headers without binding a privileged port.
        sock_port = self.server.server_port
        with patch.object(self.server, "server_port", 80):
            for method, host, origin, expected in (
                ("GET", "127.0.0.1", None, 200), ("POST", "localhost:80", "http://localhost", 201),
                ("POST", "127.0.0.1", "http://127.0.0.1:80", 201),
                ("GET", "other.example", None, 403), ("POST", "localhost", "http://127.0.0.1", 403),
            ):
                with self.subTest(method=method, host=host, origin=origin):
                    conn = http.client.HTTPConnection("127.0.0.1", sock_port, timeout=5)
                    headers = {"Host": host, "Content-Type": "application/json"}
                    if origin:
                        headers["Origin"] = origin
                    try:
                        conn.request(method, "/api/games", json.dumps({"request": str(uuid4())}) if method == "POST" else None, headers)
                        self.assertEqual(conn.getresponse().status, expected)
                    finally:
                        conn.close()

    def test_move_receipt_pgn_and_historical_board(self):
        gid = self.post("/api/games", {"preset": "puzzle-5", "request": str(uuid4())})["id"]
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

    def test_lost_game_creation_reply_reuses_the_game_and_workflow(self):
        command = {"preset": "puzzle-5", "request": str(uuid4())}
        self.post("/api/games", command)  # The client lost the first response after commit.
        recovered = self.post("/api/games", command)["id"]
        with cluster.connect() as db:
            rows = db.execute("SELECT id,instance FROM chess_room.game WHERE creation_request=%s",
                              (command["request"],)).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][0], recovered)
            self.assertTrue(rows[0][1])
        self.assertNotEqual(self.post("/api/games", command | {"request": str(uuid4())})["id"], recovered)
        with self.assertRaises(urllib.error.HTTPError) as conflict:
            self.post("/api/games", command | {"preset": "standard"})
        self.assertEqual(conflict.exception.code, 409)
