"""仅检查命令行传输；不启动软件，不访问电路工程。"""

import json
from pathlib import Path
import tempfile
import unittest

from eda_cli import prepare_command, WINDOWS_COMMAND_LINE_MAX


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.project = Path(self.directory.name)
        self.executable = self.project / "软件" / "lceda-pro.exe"
        self.base = ["invoke", "--session", "只读验证", "--timeout", "60000"]

    def test_small_call_preserves_inline_source_and_arguments(self):
        invocation, metadata = prepare_command(
            self.executable, [*self.base, "--code", "return __CLI__.args;",
                              "--args", '{"中文": "带空格 与 引号\\\""}'], self.project)
        self.assertEqual(metadata["mode"], "inline")
        self.assertEqual(invocation[invocation.index("--code") + 1], "return __CLI__.args;")
        self.assertEqual(json.loads(invocation[invocation.index("--args") + 1]),
                         {"中文": '带空格 与 引号"'})

    def test_large_code_and_args_are_in_payload_not_command(self):
        source = "/*" + "代码🚀" * 12000 + "*/ return __CLI__.args;"
        arguments = {"routes": [[index, "信号网"] for index in range(12000)]}
        code_file = self.project / "调用代码.js"
        args_file = self.project / "调用参数.json"
        code_file.write_text(source, encoding="utf-8-sig")
        args_file.write_text(json.dumps(arguments, ensure_ascii=False), encoding="utf-8-sig")
        invocation, metadata = prepare_command(self.executable, self.base, self.project,
                                               code_file, args_file)
        self.assertEqual(metadata["mode"], "file")
        self.assertLess(metadata["command_line_utf16_units"], 2000)
        self.assertGreater(metadata["inline_command_line_utf16_units"], WINDOWS_COMMAND_LINE_MAX)
        self.assertNotIn("--args", invocation)
        payload = json.loads(Path(metadata["payload_file"]).read_text(encoding="utf-8"))
        self.assertEqual(payload, {"code": source, "hasArgs": True, "args": arguments})
        self.assertEqual(Path(metadata["payload_file"]).stat().st_size, metadata["payload_bytes"])

    def test_force_file_distinguishes_no_arguments_from_null(self):
        _, none_metadata = prepare_command(self.executable, [*self.base, "--code", "return 1;"],
                                           self.project, transport="file")
        _, null_metadata = prepare_command(self.executable,
                                           [*self.base, "--code=return 1;", "--args=null"],
                                           self.project, transport="file")
        none_payload = json.loads(Path(none_metadata["payload_file"]).read_text(encoding="utf-8"))
        null_payload = json.loads(Path(null_metadata["payload_file"]).read_text(encoding="utf-8"))
        self.assertFalse(none_payload["hasArgs"])
        self.assertTrue(null_payload["hasArgs"])

    def test_forced_inline_rejects_long_call_before_launch(self):
        with self.assertRaisesRegex(ValueError, "Windows 上限"):
            prepare_command(self.executable, [*self.base, "--code", "x" * 40000],
                            self.project, transport="inline")

    def test_duplicate_source_is_rejected(self):
        code_file = self.project / "code.js"
        code_file.write_text("return 1;", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "不能同时使用"):
            prepare_command(self.executable, [*self.base, "--code", "return 2;"],
                            self.project, code_file=code_file)

    def test_registered_function_without_source_does_not_fake_file_support(self):
        with self.assertRaisesRegex(ValueError, "文件传输需要调用代码"):
            prepare_command(self.executable, [*self.base, "--fn", "run", "--args", '"' + "x" * 40000 + '"'],
                            self.project)


if __name__ == "__main__":
    unittest.main()
