# SPDX-FileCopyrightText: 2026 Kova Hand Project
# SPDX-License-Identifier: MIT

import unittest

from motion_plan import (
    AngleStep,
    MotionPlanError,
    PoseStep,
    WaitStep,
    load_gesture_presets,
    parse_motion_plan,
)


class MotionPlanTests(unittest.TestCase):
    ANGLE_RANGES = ((0, 180),) * 6

    def test_single_pose(self):
        plan = parse_motion_plan("H:0,25,50,75,100,-")
        self.assertEqual(plan, [PoseStep((0, 25, 50, 75, 100, None))])

    def test_sequence(self):
        plan = parse_motion_plan(
            "H:100,100,100,100,0,0\nW:500\n"
            "H:0,100,100,100,0,0\nW:500\n"
            "H:0,0,100,100,0,0\nW:500\n"
            "H:0,0,0,100,0,0\nW:500\n"
            "H:0,0,0,0,0,0"
        )
        self.assertEqual(len(plan), 9)
        self.assertIsInstance(plan[1], WaitStep)
        self.assertEqual(plan[1].milliseconds, 500)

    def test_preset(self):
        presets = load_gesture_presets()
        self.assertEqual(
            parse_motion_plan("P:6", presets),
            [PoseStep((100, 100, 100, 0, 0, 0))],
        )

    def test_number_presets_include_seven_and_eight(self):
        presets = load_gesture_presets()
        plan = parse_motion_plan(
            "P:7\nW:1500\nP:8",
            presets,
        )

        self.assertEqual(plan[0], PoseStep((0, 100, 100, 100, 0, 0)))
        self.assertEqual(plan[1], WaitStep(1500))
        self.assertEqual(plan[2], PoseStep((65, 65, 100, 100, 65, 100)))

    def test_rejects_unknown_preset(self):
        with self.assertRaises(MotionPlanError):
            parse_motion_plan("P:unknown", load_gesture_presets())

    def test_rejects_delay_only(self):
        with self.assertRaises(MotionPlanError):
            parse_motion_plan("W:2000")

    def test_accepts_twenty_steps(self):
        plan = parse_motion_plan("\n".join(["H:0,-,-,-,-,-"] * 20))
        self.assertEqual(len(plan), 20)

    def test_rejects_plan_without_any_motion(self):
        with self.assertRaisesRegex(MotionPlanError, "沒有任何可執行"):
            parse_motion_plan("H:-,-,-,-,-,-\nW:1000\nH:-,-,-,-,-,-")

    def test_rejects_more_than_twenty_steps(self):
        with self.assertRaises(MotionPlanError):
            parse_motion_plan("\n".join(["H:-,-,-,-,-,-"] * 21))

    def test_rejects_invalid_value(self):
        with self.assertRaises(MotionPlanError):
            parse_motion_plan("H:101,0,0,0,0,0")

    def test_exact_motor_angles(self):
        plan = parse_motion_plan(
            "A:30,-,-,-,-,90", angle_ranges=self.ANGLE_RANGES
        )
        self.assertEqual(plan, [AngleStep((30, None, None, None, None, 90))])

    def test_rejects_angle_outside_motor_range(self):
        ranges = ((10, 40),) + self.ANGLE_RANGES[1:]
        with self.assertRaises(MotionPlanError):
            parse_motion_plan("A:41,-,-,-,-,-", angle_ranges=ranges)


if __name__ == "__main__":
    unittest.main()
