#!/usr/bin/env python3
from pathlib import Path

path = Path("tests/test_init.py")
text = path.read_text(encoding="utf-8")

# Existing glibc-aio tests focus on installation/index behavior. Keep those call-count
# assertions isolated from the new library-download behavior; dedicated tests below
# exercise the compact /glibc library itself.
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

# First anchor occurs in the first install test. Third anchor occurs in both the
# update-existing and legacy tests; replace all occurrences there.
if "test_glibc_all_in_one_v2_installs_editable_cli_and_index" not in text:
    raise SystemExit("glibc tests not found")
if "configure_glibc_library = mock.Mock(return_value=True)" not in text:
    if anchors[0] not in text or anchors[1] not in text or anchors[2] not in text:
        raise SystemExit("glibc test anchors changed")
    text = text.replace(anchors[0], replacements[0], 1)
    text = text.replace(anchors[1], replacements[1], 1)
    text = text.replace(anchors[2], replacements[2])

path.write_text(text, encoding="utf-8")
