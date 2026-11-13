"""IoT installation and container lifecycle regressions, without host mutation."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import init

SPEC = importlib.util.spec_from_file_location("iot_lab", init.ROOT / "iot/lab.py")
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)


class IoTTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="iot lab ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("Dockerfile", "entrypoint.sh", "USAGE.md"):
            (self.root / name).write_text((init.ROOT / "iot" / name).read_text(encoding="utf-8"), encoding="utf-8")
        (self.root / "config.json").write_text(json.dumps({
            "firmae": str(self.root / "source checkout"), "revision": init.FIRMAE_REVISION}))
        self.lab = lab.Lab(self.root)

    def test_iot_check_routes_without_installing_or_requesting_sudo(self):
        with mock.patch.object(init, "Bootstrap") as constructor:
            b = constructor.return_value
            b.iot_only.return_value = 0
            self.assertEqual(init.main(["--iot-check"]), 0)
            b.iot_only.assert_called_once_with(check=True)
            b.install.assert_not_called()
            b.require_sudo.assert_not_called()
        b = init.Bootstrap()
        with mock.patch.object(b, "verify_iot"), mock.patch.object(b, "install_iot_environment") as install, \
                mock.patch.object(b, "preflight") as preflight:
            self.assertEqual(b.iot_only(check=True), 0)
            install.assert_not_called()
            preflight.assert_not_called()

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

    def test_qiling_probe_checks_cli_and_runs_cpu_instructions(self):
        b = init.Bootstrap()
        python = self.root / "bin/python"
        python.parent.mkdir()
        python.touch()
        python.with_name("qltool").touch()
        with mock.patch.object(init, "QILING_DIR", self.root), \
                mock.patch.object(b, "run", return_value=subprocess.CompletedProcess([], 0)) as run, \
                mock.patch.object(b, "executable_usable", return_value=True) as cli:
            self.assertTrue(b.qiling_available())
            self.assertIn("q.run()", run.call_args[0][0][-1])
            cli.assert_called_once_with(str(python.with_name("qltool")), ["--help"])

    def test_qiling_repair_uses_own_interpreter_and_pinned_source(self):
        b = init.Bootstrap()
        with mock.patch.object(init, "QILING_DIR", self.root / "qiling"), \
                mock.patch.object(b, "qiling_available", side_effect=[False, True]), \
                mock.patch.object(b, "install_uv", return_value=True), \
                mock.patch.object(b, "uv_executable", return_value="uv"), \
                mock.patch.object(b, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertTrue(b.install_qiling())
            command = run.call_args[0][0]
            self.assertIn(str(self.root / "qiling/bin/python"), command)
            self.assertIn(init.QILING_SPEC, command)
            self.assertNotIn("--system", command)


if __name__ == "__main__":
    unittest.main()
