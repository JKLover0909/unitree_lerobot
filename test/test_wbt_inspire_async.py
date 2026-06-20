import unittest

import numpy as np

from unitree_lerobot.eval_robot.wbt_inspire_hybrid_infer import (
    InferenceResult,
    merge_inference_result,
)


class WbtInspireAsyncTest(unittest.TestCase):
    def test_merge_skips_stale_actions_and_preserves_chunk_offsets(self):
        chunk = np.arange(5 * 26, dtype=np.float32).reshape(5, 26)
        result = InferenceResult(anchor=10, action_chunk=chunk, inference_s=1.25)
        queue = {}

        inserted = merge_inference_result(
            queue,
            result,
            current_timestep=12,
            actions_per_inference=4,
            stop_timestep=20,
        )

        self.assertEqual(inserted, 2)
        self.assertEqual(sorted(queue), [12, 13])
        np.testing.assert_array_equal(queue[12].predicted, chunk[2])
        np.testing.assert_array_equal(queue[13].predicted, chunk[3])
        self.assertEqual(queue[12].chunk_offset, 2)
        self.assertEqual(queue[13].chunk_offset, 3)
        self.assertTrue(queue[12].report_inference)
        self.assertFalse(queue[13].report_inference)

    def test_merge_stops_at_episode_boundary(self):
        chunk = np.zeros((100, 26), dtype=np.float32)
        result = InferenceResult(anchor=50, action_chunk=chunk, inference_s=2.0)
        queue = {}

        inserted = merge_inference_result(
            queue,
            result,
            current_timestep=50,
            actions_per_inference=100,
            stop_timestep=55,
        )

        self.assertEqual(inserted, 5)
        self.assertEqual(sorted(queue), [50, 51, 52, 53, 54])


if __name__ == "__main__":
    unittest.main()
