"""检查实际屏幕轨迹的拟合及无效采样拒绝，不连接蓝牙设备。"""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ble_tool import fit_horizontal_trace


class TraceFitTests(unittest.TestCase):
    def test_both_signed_diagonals(self):
        for degrees in (-30, 0, 30):
            slope = math.tan(math.radians(degrees))
            segments = []
            for i in range(100):
                x = (5 + i % 7) * (1 if i < 50 else -1)
                segments.append((x, slope*x + (.1 if i % 2 else -.1)))
            self.assertAlmostEqual(fit_horizontal_trace(segments)["角度"], degrees, delta=.1)

    def test_no_movement_rejected(self):
        with self.assertRaises(ValueError):
            fit_horizontal_trace([(0, 0)] * 100)

    def test_one_way_rejected(self):
        with self.assertRaises(ValueError):
            fit_horizontal_trace([(5, 3)] * 100)

    def test_inconsistent_trace_rejected(self):
        with self.assertRaises(ValueError):
            fit_horizontal_trace([(5 if i < 50 else -5, 20 if i % 2 else -20) for i in range(100)])


if __name__ == "__main__":
    unittest.main()
