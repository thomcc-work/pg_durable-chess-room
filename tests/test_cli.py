import subprocess
import sys
import unittest


class CliTests(unittest.TestCase):
    def test_legacy_module_opens_the_same_cli(self):
        def help_text(module):
            return subprocess.check_output([sys.executable, "-m", module, "--help"], text=True)

        canonical = help_text("chess_room")
        self.assertIn("usage: uv run -m chess_room", canonical)
        self.assertEqual(help_text("mate"), canonical)
