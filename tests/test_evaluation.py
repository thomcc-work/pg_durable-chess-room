import unittest

from mate.evaluation import canned_reply, comparison, grade, prompt


class EvaluationTests(unittest.TestCase):
    def test_moves_and_format(self):
        for text, expected in (
            (" c7c8r\n", ("mate", "c7c8r")),
            ("c7c8q", ("mate", "c7c8q")),
            ("c7c8b", ("miss", "c7c8b")),
            ("c8=Q#", ("malformed", "c8=Q#")),
            ("c7c8q or c7c8r", ("malformed", "c7c8q or c7c8r")),
        ):
            with self.subTest(text=text):
                reply = canned_reply(200, text)
                self.assertEqual(grade(200, "text", reply["body"], ["c7c8q", "c7c8r"]), expected)

    def test_non_success_is_not_a_chess_verdict(self):
        self.assertEqual(grade(429, "text", "not even JSON", []), ("provider_error", None))

    def test_bad_chat_envelopes(self):
        for encoding, body in (
            ("base64", "Y2hlc3M="), ("text", "not JSON"), ("text", None),
            ("text", '{"choices":[]}'), ("text", '{"choices":[{"message":{"content":42}}]}'),
            ("text", r'{"choices":[{"message":{"content":"\u0000"}}]}'),
        ):
            with self.subTest(body=body):
                self.assertEqual(grade(200, encoding, body, []), ("response_error", None))

    def test_prompt_b_adds_only_the_reply_check(self):
        fen = "7k/5K2/8/8/8/8/R7/8 w - - 0 1"
        hint = "Before choosing, check that the opponent has no legal reply. "
        self.assertIn(hint, prompt("B", fen))
        self.assertEqual(prompt("B", fen).replace(hint, ""), prompt("A", fen))
        self.assertTrue(prompt("A", fen).endswith(f"FEN: {fen}"))

    def test_compare_only_gradable_pairs(self):
        for a, b, expected in (
            ("mate", "miss", "B regression"), ("miss", "mate", "B gain"),
            ("mate", "mate", "same"), ("miss", "miss", "same"),
            ("malformed", "mate", "needs attention"), ("mate", "provider_error", "needs attention"),
            ("recorded", "pending", "unfinished"), ("workflow_error", "miss", "needs attention"),
        ):
            with self.subTest(a=a, b=b):
                self.assertEqual(comparison(a, b), expected)
