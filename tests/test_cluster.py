import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chess_room import cluster


class ClusterOwnershipTests(unittest.TestCase):
    def test_refuses_copied_metadata_without_invoking_pg_ctl(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root) / "copy"
            data = state / "data"
            data.mkdir(parents=True)
            marker = state / "pg-bindir"
            marker.write_text("/bin\n")
            foreign = Path(root) / "original/data"
            (data / "postmaster.opts").write_text(f'/bin/postgres "-D" "{foreign}"\n')
            owner = state / "pg-data-owner"
            with patch.multiple(cluster, STATE=state, DATA=data, MARKER=marker), patch("subprocess.run") as ctl:
                for legacy in (True, False):
                    if not legacy:
                        owner.write_text(f"{foreign}\n")
                    for action in ("start", "restart", "stop"):
                        with self.subTest(legacy=legacy, action=action), self.assertRaises(ValueError):
                            cluster.pg_ctl(action)
                owner.write_text(f"{data}\n")
                (data / "postmaster.pid").write_text(f"123\n{foreign}\n")
                with self.assertRaises(ValueError):
                    cluster.pg_ctl("stop")
                ctl.assert_not_called()
