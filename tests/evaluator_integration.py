import io
import unittest
from contextlib import redirect_stdout
from uuid import uuid4

from chess_room import cluster, experiment


class RetainedResponses(unittest.TestCase):
    def test_pruned_workflow_without_a_capture_is_not_left_pending_or_reissued(self):
        cluster.use_private_socket()
        with cluster.connect() as db:
            run = experiment.get_run(db, experiment.new_run(db, 1))
            db.execute("UPDATE chess_room.cell SET instance=%s WHERE run_id=%s AND variant='A'",
                       (uuid4().hex, run.id))
            with redirect_stdout(io.StringIO()) as out:
                experiment.finish(db, run)
            self.assertIn("expired without a recorded response", out.getvalue())
            self.assertEqual(db.execute("SELECT verdict FROM chess_room.cell WHERE run_id=%s ORDER BY variant",
                                        (run.id,)).fetchall(), [("workflow_error",), ("mate",)])

    def test_grades_captured_reply_and_retains_failure_after_workflow_history_is_gone(self):
        cluster.use_private_socket()
        with cluster.connect() as db:
            run = experiment.get_run(db, experiment.new_run(db, 2))
            first, failed = db.execute("SELECT id FROM chess_room.cell WHERE run_id=%s AND board=1 ORDER BY variant",
                                       (run.id,)).fetchall()
            # Give the captured cell an instance with no retained metadata, as after pruning.
            db.execute("UPDATE chess_room.cell SET instance=%s, http_status=200, encoding='text', "
                       "body=fixture->>'body' WHERE id=%s", (uuid4().hex, first[0]))
            inst, = db.execute("UPDATE chess_room.cell SET instance=df.start('SELECT 1/0') WHERE id=%s "
                               "RETURNING instance", failed).fetchone()
            self.assertEqual(db.execute("SELECT df.await_instance(%s,15)", (inst,)).fetchone(), ("failed",))
            with redirect_stdout(io.StringIO()) as out:
                experiment.scorecard(db, run)
            self.assertIn("division by zero", out.getvalue())
            db.execute("UPDATE chess_room.cell SET instance=%s WHERE id=%s", (uuid4().hex, failed[0]))
            with redirect_stdout(io.StringIO()) as out:
                experiment.finish(db, run)
            self.assertIn("division by zero", out.getvalue())
            self.assertEqual([v for v, in db.execute("SELECT verdict FROM chess_room.cell WHERE run_id=%s "
                                                     "ORDER BY board,variant", (run.id,))],
                             ["miss", "workflow_error", "mate", "miss"])
            self.assertEqual(db.execute("SELECT count(*) FROM chess_room.fixture_attempt a JOIN chess_room.cell c "
                                        "ON c.id=a.cell_id WHERE c.run_id=%s AND c.board=1", (run.id,)).fetchone(), (0,))
