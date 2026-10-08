import unittest
import sys
from pathlib import Path

TESTBED_ROOT = Path(__file__).resolve().parents[1]
if str(TESTBED_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTBED_ROOT))

from core.job_enricher import classify_outcome


class JobEnricherOutcomeTests(unittest.TestCase):
    def test_pending_when_not_finished(self):
        self.assertEqual(classify_outcome(False, 0, ""), "pending")

    def test_timeout_when_response_has_sweep_timeout_sentinel(self):
        response = '{"sweep": "timeout", "kind": "no_result"}'
        self.assertEqual(classify_outcome(True, 0, response), "timeout")

    def test_success_when_run_time_positive(self):
        self.assertEqual(classify_outcome(True, 10, '{"Result":"ok"}'), "success")

    def test_error_when_finished_and_zero_run_time(self):
        self.assertEqual(classify_outcome(True, 0, '{"error":"boom"}'), "error")

    def test_error_when_result_is_error_object_despite_run_time(self):
        # rep 1: the provider recorded its wait as run_time on failures
        response = '{"error": "No response received from container"}'
        self.assertEqual(classify_outcome(True, 9500, response), "error")

    def test_success_when_result_has_empty_error_field(self):
        self.assertEqual(classify_outcome(True, 10, '{"result": 1, "error": null}'), "success")

    def test_success_when_response_is_not_json(self):
        self.assertEqual(classify_outcome(True, 10, "<!DOCTYPE html>"), "success")


if __name__ == "__main__":
    unittest.main()
