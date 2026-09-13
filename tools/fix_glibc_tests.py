#!/usr/bin/env python3
from pathlib import Path

path = Path("tests/test_init.py")
text = path.read_text(encoding="utf-8")

anchors = [
    "            self.bootstrap.install_command_wrapper = mock.Mock(return_value=True)\n            self.bootstrap.glibc_aio_runtime_available = mock.Mock(\n                side_effect=[False, True]\n            )\n",
    "            self.bootstrap.install_command_wrapper = mock.Mock()\n            self.bootstrap.run = mock.Mock(\n                return_value=subprocess.CompletedProcess([\"glibc-aio\"], 0)\n            )\n",
    "            self.bootstrap.install_command_wrapper = mock.Mock(return_value=True)\n            self.bootstrap.glibc_aio_runtime_available = mock.Mock(return_value=True)\n            with mock.patch.object(MODULE, \"GLIBC_AIO_DIR\", destination):\n",
]
replacements = [
    anchors[0] + "            self.bootstrap.configure_glibc_library = mock.Mock(return_value=True)\n",
    anchors[1] + "            self.bootstrap.configure_glibc_library = mock.Mock(return_value=True)\n",
    anchors[2].replace(
        "            with mock.patch.object(MODULE, \"GLIBC_AIO_DIR\", destination):\n",
        "            self.bootstrap.configure_glibc_library = mock.Mock(return_value=True)\n"
        "            with mock.patch.object(MODULE, \"GLIBC_AIO_DIR\", destination):\n",
    ),
]

if "test_glibc_all_in_one_v2_installs_editable_cli_and_index" not in text:
    raise SystemExit("glibc tests not found")
if "configure_glibc_library = mock.Mock(return_value=True)" not in text:
    if anchors[0] not in text or anchors[1] not in text or anchors[2] not in text:
        raise SystemExit("glibc test anchors changed")
    text = text.replace(anchors[0], replacements[0], 1)
    text = text.replace(anchors[1], replacements[1], 1)
    text = text.replace(anchors[2], replacements[2])

old = '''            commands = [call.args[0] for call in self.bootstrap.run.call_args_list]\n            self.assertEqual(len(commands), 2)\n            self.assertEqual(commands[0][-2:], ["pyelftools", "zstandard"])\n            self.assertEqual(commands[1][-2:], ["--editable", "."])\n            self.assertEqual(self.bootstrap.failures, [])\n'''
new = '''            commands = [call.args[0] for call in self.bootstrap.run.call_args_list]\n            self.assertEqual(len(commands), 3)\n            self.assertEqual(commands[0][-2:], ["pyelftools", "zstandard"])\n            self.assertEqual(commands[1][-2:], ["--editable", "."])\n            self.assertEqual(commands[2][-2:], ["mirror", "update"])\n            self.assertEqual(self.bootstrap.failures, [])\n'''
if old not in text:
    raise SystemExit("update-mode glibc test anchor changed")
text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
