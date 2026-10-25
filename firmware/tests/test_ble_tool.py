"""检查实际屏幕轨迹的拟合及无效采样拒绝，不连接蓝牙设备。"""
import math
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ble_tool import fit_horizontal_trace, image_elf_hash, image_payload, verify_running_image


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


class UpdateIdentityTests(unittest.TestCase):
    def image(self):
        payload = bytearray(320)
        payload[0] = 0xE9
        struct.pack_into("<H", payload, 12, 9)
        struct.pack_into("<I", payload, 32, 0xABCD5432)
        payload[176:208] = bytes(range(32))
        marker = b"GunMouse SuperMini\0"
        payload[288:288 + len(marker)] = marker
        return payload

    def test_expected_build_can_be_identified(self):
        payload = self.image()
        expected = bytes(range(32)).hex()
        self.assertEqual(image_elf_hash(payload), expected)
        verify_running_image({"slot": "app0"}, {"slot": "app1", "elf": expected}, expected)

    def test_other_binary_types_and_projects_are_rejected(self):
        for offset, value in ((0, 0), (12, 5), (32, 0), (288, 0), (176, 255)):
            payload = self.image()
            if offset == 176:
                payload[176:208] = b"\xff" * 32
            else:
                payload[offset] = value
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                image_elf_hash(payload)
        with self.assertRaises(ValueError):
            image_elf_hash(b"\xe9" * 100)

    def test_slot_change_alone_is_not_success(self):
        expected = bytes(range(32)).hex()
        for after in ({"slot": "app0", "elf": expected}, {"slot": "app1"},
                      {"slot": "app1", "elf": "00" * 32}):
            with self.subTest(after=after), self.assertRaises(RuntimeError):
                verify_running_image({"slot": "app0"}, after, expected)

    def test_file_is_checked_against_build_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "bin").mkdir()
            path = root / "bin" / "app.bin"
            payload = bytes(self.image())
            path.write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            manifest = root / "build-manifest.json"
            manifest.write_text(json.dumps({"artifacts": {path.name: {"sha256": digest}}}), encoding="utf-8")
            self.assertEqual(image_payload(path), (payload, digest))
            manifest.write_text(json.dumps({"artifacts": {path.name: {"sha256": "00" * 32}}}), encoding="utf-8")
            with self.assertRaises(ValueError):
                image_payload(path)


if __name__ == "__main__":
    unittest.main()
