"""Exercise interrupted setup on a separate, disposable data directory."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chess_room import cluster, experiment


class BootstrapTests(unittest.TestCase):
    def test_start_resumes_interrupted_bootstrap_without_replacing_the_server(self):
        config = cluster.bindir() / "pg_config"
        with tempfile.TemporaryDirectory(prefix="chess-init-") as root:
            state = Path(root) / ".chess-room"
            with patch.dict(os.environ, PG_CONFIG=str(config)), patch.multiple(
                cluster, STATE=state, DATA=state / "data", MARKER=state / "pg-bindir", LOG=state / "server.log"
            ):
                cluster.use_private_socket()
                connect = cluster.connect

                def interrupt_schema(user="chess_room_app"):
                    if user == "chess_room_app":
                        raise InterruptedError("before schema installation")
                    return connect(user)

                try:
                    with patch.object(cluster, "connect", interrupt_schema), self.assertRaises(InterruptedError):
                        cluster.init()
                    with connect() as db:
                        started, = db.execute("SELECT pg_postmaster_start_time()").fetchone()
                        self.assertEqual(db.execute("SELECT to_regclass('chess_room.cell')").fetchone(), (None,))
                    cluster.start()
                    with connect() as db:
                        self.assertEqual(db.execute("SELECT pg_postmaster_start_time()").fetchone(), (started,))
                        self.assertGreater(experiment.new_run(db, 1), 0)
                finally:
                    if (cluster.DATA / "postmaster.pid").exists():
                        cluster.pg_ctl("stop")
