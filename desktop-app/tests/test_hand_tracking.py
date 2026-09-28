from __future__ import annotations

import sys
import unittest
from pathlib import Path


DESKTOP_APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_APP))

import config  # noqa: E402
from main import HandTracker, finger_curl, thumb_cmc_inward, thumb_curl  # noqa: E402


class Landmark:
    def __init__(self, x: float, y: float, z: float = 0.0):
        self.x = x
        self.y = y
        self.z = z


class HandGeometryTests(unittest.TestCase):
    @staticmethod
    def _thumb_landmarks() -> list[Landmark]:
        landmarks = [Landmark(0.0, 0.0) for _ in range(21)]
        landmarks[0] = Landmark(0.0, 2.0)
        landmarks[5] = Landmark(-1.0, 0.0)
        landmarks[17] = Landmark(1.0, 0.0)
        landmarks[1] = Landmark(0.0, 0.0)
        landmarks[2] = Landmark(1.0, 0.0)
        landmarks[3] = Landmark(2.0, 0.0)
        return landmarks

    def test_finger_curl_is_not_changed_by_depth_noise(self):
        flat = [Landmark(0.0, 0.0) for _ in range(21)]
        noisy = [Landmark(0.0, 0.0) for _ in range(21)]
        points = (
            Landmark(0.0, 0.0),
            Landmark(0.0, 1.0),
            Landmark(0.6, 1.5),
            Landmark(1.1, 1.2),
        )
        for index, point in zip((5, 6, 7, 8), points):
            flat[index] = point
            noisy[index] = Landmark(point.x, point.y, 5.0 if index % 2 else -5.0)

        self.assertAlmostEqual(
            finger_curl(flat, (5, 6, 7, 8)),
            finger_curl(noisy, (5, 6, 7, 8)),
        )

    def test_thumb_cmc_is_not_changed_by_depth_noise(self):
        flat = [Landmark(0.0, 0.0) for _ in range(21)]
        noisy = [Landmark(0.0, 0.0) for _ in range(21)]
        flat[0], flat[2], flat[5] = (
            Landmark(0.0, 0.0),
            Landmark(1.0, 0.4),
            Landmark(0.2, 1.0),
        )
        noisy[0], noisy[2], noisy[5] = (
            Landmark(0.0, 0.0, -3.0),
            Landmark(1.0, 0.4, 4.0),
            Landmark(0.2, 1.0, -5.0),
        )

        self.assertAlmostEqual(thumb_cmc_inward(flat), thumb_cmc_inward(noisy))

    def test_thumb_curl_emphasizes_ip_joint(self):
        landmarks = self._thumb_landmarks()
        landmarks[4] = Landmark(2.0, 1.0)

        self.assertGreater(thumb_curl(landmarks), 0.70)

    def test_straight_thumb_is_open(self):
        landmarks = self._thumb_landmarks()
        landmarks[4] = Landmark(3.0, 0.0)

        self.assertEqual(thumb_curl(landmarks), 0.0)

    def test_backward_thumb_bend_is_not_treated_as_inward_curl(self):
        landmarks = self._thumb_landmarks()
        landmarks[4] = Landmark(2.0, -1.0)

        self.assertEqual(thumb_curl(landmarks), 0.0)


class HandSignalFilterTests(unittest.TestCase):
    def setUp(self):
        self.tracker = HandTracker.__new__(HandTracker)
        self.tracker.smoothed_controls = {}
        self.tracker.control_history = {}

    def test_single_frame_spike_is_rejected_by_median(self):
        stable = [self.tracker._smooth(0, 0.40) for _ in range(config.HAND_FILTER_WINDOW)]
        after_spike = self.tracker._smooth(0, 1.0)

        self.assertAlmostEqual(stable[-1], 0.40)
        self.assertAlmostEqual(after_spike, 0.40)

    def test_small_jitter_stays_inside_dead_zone(self):
        for channel in (0, 5):
            baseline = self.tracker._smooth(channel, 0.50)
            for measured in (0.51, 0.49, 0.52, 0.48, 0.51):
                result = self.tracker._smooth(channel, measured)

            self.assertAlmostEqual(baseline, 0.50)
            self.assertAlmostEqual(result, 0.50)

    def test_large_motion_is_rate_limited(self):
        for _ in range(config.HAND_FILTER_WINDOW):
            self.tracker._smooth(0, 0.0)
        for _ in range(config.HAND_FILTER_WINDOW):
            previous = self.tracker.smoothed_controls[0]
            result = self.tracker._smooth(0, 1.0)
            self.assertLessEqual(
                result - previous,
                config.HAND_MAX_DELTA_PER_UPDATE + 1e-9,
            )

        self.assertGreater(result, 0.0)

if __name__ == "__main__":
    unittest.main()
