import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_PATH = ROOT / "integration_tests" / "scenarios.json"


class IntegrationHarnessTests(unittest.TestCase):
    def test_all_scenarios_reference_existing_workflow_fixtures(self):
        scenarios = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
        self.assertGreater(len(scenarios), 0)
        for scenario in scenarios:
            workflow_path = ROOT / scenario["workflow"]
            self.assertTrue(
                workflow_path.exists(),
                f"Missing workflow fixture for scenario {scenario['id']}: {workflow_path}",
            )

    def test_known_failure_scenarios_are_tier_one_issue_targets(self):
        scenarios = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
        known_failures = [scenario for scenario in scenarios if scenario["expected"] == "known_failure"]
        self.assertGreater(len(known_failures), 0)
        for scenario in known_failures:
            self.assertEqual(scenario["tier"], 1)


if __name__ == "__main__":
    unittest.main()
