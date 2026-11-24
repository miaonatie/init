"""FirmAE container lifecycle regressions, without host mutation."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

IOT_DIR = Path(__file__).resolve().parents[1] / "iot"
SPEC = importlib.util.spec_from_file_location("iot_lab", IOT_DIR / "lab.py")
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)


class IoTTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="iot lab ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("Dockerfile", "entrypoint.sh", "USAGE.md"):
            (self.root / name).write_text((IOT_DIR / name).read_text(encoding="utf-8"), encoding="utf-8")
        (self.root / "config.json").write_text(json.dumps({
            "firmae": str(self.root / "source checkout"), "revision": "test-revision"}))
        self.lab = lab.Lab(self.root)

    def test_check_without_docker_is_read_only_and_explicitly_pending(self):
        with mock.patch.object(self.lab, "source_ready", return_value=True), \
                mock.patch.object(self.lab, "connect", return_value=False), \
                mock.patch.object(self.lab, "dc") as dc:
            self.assertEqual(self.lab.check(), 3)
            dc.assert_not_called()

    def test_build_defers_only_when_daemon_unavailable(self):
        with mock.patch.object(self.lab, "source_ready", return_value=True), \
                mock.patch.object(self.lab, "connect", return_value=False), \
                mock.patch.object(lab.platform, "machine", return_value="x86_64"), \
                mock.patch.object(self.lab, "dc") as dc:
            self.assertEqual(self.lab.build(if_available=True), 3)
            dc.assert_not_called()
            with self.assertRaisesRegex(RuntimeError, "Docker daemon"):
                self.lab.build()

    def test_image_fingerprint_changes_with_assets(self):
        original = self.lab.image
        with (self.root / "entrypoint.sh").open("a") as stream:
            stream.write("\n# fix\n")
        self.assertNotEqual(original, lab.Lab(self.root).image)

    def test_daemon_permissions_use_sudo_without_changing_lab_identity(self):
        results = [subprocess.CompletedProcess([], 1), subprocess.CompletedProcess([], 0)]
        with mock.patch.object(lab.shutil, "which", return_value="/bin/tool"), \
                mock.patch.object(lab.os, "geteuid", return_value=1000), \
                mock.patch.object(lab, "run", side_effect=results) as run:
            self.assertTrue(self.lab.connect())
            self.assertEqual(self.lab.docker, ["sudo", "-n", "docker"])
            self.assertEqual(run.call_count, 2)

    def test_start_uses_separate_network_loopback_web_and_persistent_storage(self):
        with mock.patch.object(self.lab, "require_docker"), \
                mock.patch.object(self.lab, "image_ready", return_value=True), \
                mock.patch.object(self.lab, "inspect_container", return_value=None), \
                mock.patch.object(self.lab, "dc", return_value=subprocess.CompletedProcess([], 0)) as dc:
            self.lab.start()
            command = dc.call_args_list[0][0][0]
            self.assertIn("--privileged", command)
            self.assertIn("127.0.0.1:18080:18080", command)
            self.assertNotIn("host", command)
            self.assertNotIn("/var/run/docker.sock", " ".join(command))
            self.assertEqual(sum("type=volume" in arg for arg in command), 4)

    def test_old_container_is_preserved_and_upgrade_is_actionable(self):
        with mock.patch.object(self.lab, "require_docker"), \
                mock.patch.object(self.lab, "image_ready", return_value=True), \
                mock.patch.object(self.lab, "inspect_container", return_value={"Config": {"Image": "old"}}), \
                mock.patch.object(self.lab, "dc") as dc:
            with self.assertRaisesRegex(RuntimeError, "recreate"):
                self.lab.start()
            dc.assert_not_called()

    def test_firmware_path_with_spaces_is_copied_to_safe_stable_guest_path(self):
        firmware = self.root / "firmware with spaces $(literal).bin"
        firmware.write_bytes(b"firmware fixture")
        with mock.patch.object(self.lab, "start"), mock.patch.object(self.lab, "dc") as dc, \
                mock.patch.object(self.lab, "execute", return_value=0) as execute:
            self.assertEqual(self.lab.emulate("-c", "dlink", str(firmware)), 0)
            self.assertEqual(dc.call_args[0][0][1], str(firmware))
            command = execute.call_args[0][0]
            self.assertEqual(command[:3], ["./run.sh", "-c", "dlink"])
            self.assertRegex(command[3], r"^/firmwares/[a-f0-9]{64}\.bin$")
            with self.assertRaises(ValueError):
                self.lab.emulate("-c", "dlink; id", str(firmware))

    def test_familiar_firmae_mode_parsing_and_help_need_no_runtime(self):
        with mock.patch.object(lab, "Lab") as constructor:
            constructor.return_value.emulate.return_value = 0
            self.assertEqual(lab.main(["-r", "dlink", "firmware with spaces.bin"]), 0)
            constructor.return_value.emulate.assert_called_once_with("-r", "dlink", "firmware with spaces.bin")
        with mock.patch.object(lab, "Lab") as constructor:
            with self.assertRaises(SystemExit) as context:
                lab.main(["--help"])
            self.assertEqual(context.exception.code, 0)
            constructor.assert_not_called()

if __name__ == "__main__":
    unittest.main()
