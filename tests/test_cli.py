import subprocess
import sys
import unittest


class CliTests(unittest.TestCase):
    def test_game_and_evaluator_share_the_chess_room_cli(self):
        help_text = subprocess.check_output([sys.executable, "-m", "chess_room", "--help"], text=True)
        self.assertIn("usage: uv run -m chess_room", help_text)
        self.assertIn("game-demo", help_text)
        self.assertIn("new-live", help_text)
