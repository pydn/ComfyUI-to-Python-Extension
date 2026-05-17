"""Tests for planner readability helpers."""

import time
import unittest

from comfyui_to_python.generator.planner import WorkflowPlanner


class ScaleNode:
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"value": ("INT",)}}

    def run(self, value):
        return (value,)


class WorkflowPlannerReadabilityTest(unittest.TestCase):
    def test_required_input_helper_detects_missing_values(self):
        input_types = {"required": {"prompt": ("STRING",), "seed": ("INT",)}}

        self.assertTrue(
            WorkflowPlanner._node_has_missing_required_inputs(
                input_types, {"prompt": "hello"}
            )
        )
        self.assertFalse(
            WorkflowPlanner._node_has_missing_required_inputs(
                input_types, {"prompt": "hello", "seed": 1}
            )
        )

    def test_hidden_input_helper_adds_allowed_runtime_values(self):
        inputs = {}
        input_types = {
            "hidden": {
                "unique_id": "UNIQUE_ID",
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            }
        }

        WorkflowPlanner._apply_hidden_inputs(
            inputs,
            input_types,
            ["unique_id", "prompt", "extra_pnginfo"],
        )

        self.assertIsInstance(inputs["unique_id"], int)
        self.assertEqual(inputs["prompt"], {"variable_name": "prompt"})
        self.assertEqual(inputs["extra_pnginfo"], {"variable_name": "extra_pnginfo"})

    def test_large_workflow_build_plan_stays_linear_enough(self):
        planner = WorkflowPlanner(
            node_class_mappings={"ScaleNode": ScaleNode},
            base_node_class_mappings={"ScaleNode": ScaleNode},
        )
        load_order = [
            (
                str(index),
                {"class_type": "ScaleNode", "inputs": {"value": index}},
                False,
            )
            for index in range(300)
        ]

        started = time.perf_counter()
        plan = planner.build_plan(load_order, workflow_data={})
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 1.0)
        self.assertEqual(len(plan.loop_code), 300)
        self.assertEqual(len(plan.special_functions_code), 1)


if __name__ == "__main__":
    unittest.main()
