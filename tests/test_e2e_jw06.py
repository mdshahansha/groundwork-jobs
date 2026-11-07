"""E2E JW-06: pinning a model stales a pending task, refuses other-model output, and refreshes rankings."""

import unittest

from e2e_support import CV, E2E
from test_jw_ranking import assessment, policy


class PinRefreshE2E(E2E):
    def test_pin_refresh_and_model_mismatch(self):
        _, claim = self.profile()
        self.ok("policy-set", {"policy": policy()})
        job = self.job()
        mapping = [{"index": 0, "state": "supported", "claim_id": claim}]
        first = self.ok("rank", {"job_id": job, "mapping": mapping, "assessment": assessment()})
        self.assertEqual([job], self.ok("rankings-refresh", {})["unchanged"])
        pending = self.ok("task-create", {"job_id": job, "kind": "draft_cv", "consent": True})["task_id"]
        self.ok("model-pin", {"model": "model-a"})
        self.fails("stale_input", "task-packet", {"task_id": pending})
        refreshed = self.ok("rankings-refresh", {})["refreshed"]
        self.assertEqual(job, refreshed[0]["job_id"])
        self.assertNotEqual(first["ranking_id"], refreshed[0]["ranking_id"])
        letter = self.ok("task-create", {"job_id": job, "kind": "draft_letter", "consent": True})["task_id"]
        response = {"output": {"assertions": [{"text": CV, "claim_id": claim}]},
                    "usage": {"model": "model-b", "input_tokens": None, "output_tokens": None}}
        self.fails("model_mismatch", "task-submit", {"task_id": letter, "response": response})
        response["usage"]["model"] = "model-a"
        self.assertEqual("completed", self.ok("task-submit", {"task_id": letter, "response": response})["state"])


if __name__ == "__main__":
    unittest.main()
