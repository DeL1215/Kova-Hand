import unittest

from motion_plan import (
    MotionPlanError,
    PoseStep,
    WaitStep,
    load_gesture_presets,
    parse_motion_plan,
)


class MotionPlanTests(unittest.TestCase):
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

    def test_rejects_unknown_preset(self):
        with self.assertRaises(MotionPlanError):
            parse_motion_plan("P:unknown", load_gesture_presets())

    def test_rejects_delay_only(self):
        with self.assertRaises(MotionPlanError):
            parse_motion_plan("W:2000")

    def test_accepts_twenty_steps(self):
        plan = parse_motion_plan("\n".join(["H:-,-,-,-,-,-"] * 20))
        self.assertEqual(len(plan), 20)

    def test_rejects_more_than_twenty_steps(self):
        with self.assertRaises(MotionPlanError):
            parse_motion_plan("\n".join(["H:-,-,-,-,-,-"] * 21))

    def test_rejects_invalid_value(self):
        with self.assertRaises(MotionPlanError):
            parse_motion_plan("H:101,0,0,0,0,0")


if __name__ == "__main__":
    unittest.main()
