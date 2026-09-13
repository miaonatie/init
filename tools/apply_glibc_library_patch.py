#!/usr/bin/env python3
import re
from pathlib import Path

path = Path("init.py")
text = path.read_text(encoding="utf-8")

needle = 'GLIBC_AIO_DEPENDENCIES = ("pyelftools", "zstandard")\n'
replacement = needle + 'GLIBC_LIBRARY_ROOT = Path("/glibc")\nGLIBC_LIBRARY_ARCHES = ("amd64", "i386")\n'
if "GLIBC_LIBRARY_ROOT" not in text:
    if needle not in text:
        raise SystemExit("glibc constants anchor not found")
    text = text.replace(needle, replacement, 1)

start = text.index("    def install_glibc_all_in_one(self) -> None:\n")
end = text.index("    def glibc_aio_runtime_available(self) -> bool:\n", start)
new_block = '''    def install_glibc_all_in_one(self) -> None:
        project_file = GLIBC_AIO_DIR / "pyproject.toml"
        runtime_ready = project_file.exists() and self.glibc_aio_runtime_available()
        index_ready = self.glibc_aio_index_available()
        if not project_file.exists() and (GLIBC_AIO_DIR / ".git").exists():
            self.info("glibc-all-in-one: updating the legacy checkout to v2")
            update = self.run(
                [
                    "git", "-C", str(GLIBC_AIO_DIR), "pull", "--ff-only",
                    "origin", "master",
                ],
                check=False,
                network=True,
                timeout=300,
                env={"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "true"},
            )
            if update.returncode != 0:
                self.failures.append("glibc-all-in-one v2 source update failed")
                return

        if not project_file.exists():
            self.failures.append(
                "glibc-all-in-one v2 metadata not found after repository installation"
            )
            return

        if self.update_existing or not runtime_ready:
            python = self.system_python()
            pip_base = [
                python, "-m", "pip", "install",
                "--disable-pip-version-check", *PIP_NETWORK_OPTIONS, "--upgrade",
            ]
            self.info("glibc-all-in-one: ensuring the v2 Python dependencies")
            dependencies = self.run(
                [*pip_base, *GLIBC_AIO_DEPENDENCIES],
                cwd=GLIBC_AIO_DIR,
                sudo=not self.ubuntu_before("24.04"),
                check=False,
                timeout=300,
                env={"PIP_ROOT_USER_ACTION": "ignore", "PIP_BREAK_SYSTEM_PACKAGES": "1"},
            )
            if dependencies.returncode != 0:
                self.failures.append("glibc-all-in-one v2 dependency installation failed")
                return

            self.info("glibc-all-in-one: installing the repository as an editable package")
            editable = self.run(
                [*pip_base, "--editable", "."],
                cwd=GLIBC_AIO_DIR,
                sudo=not self.ubuntu_before("24.04"),
                check=False,
                timeout=300,
                env={"PIP_ROOT_USER_ACTION": "ignore", "PIP_BREAK_SYSTEM_PACKAGES": "1"},
            )
            if editable.returncode != 0:
                self.failures.append("glibc-all-in-one v2 editable installation failed")
                return

            wrapper = self.repository_command_wrapper(
                GLIBC_AIO_DIR,
                [python, "-c", "from glibc_aio.cli.main import main; main()"],
            )
            if not self.install_command_wrapper(GLIBC_AIO_COMMAND, wrapper):
                self.failures.append("glibc-all-in-one v2 command wrapper installation failed")
                return
            self._extend_path()
            self._glibc_runtime_cache = None
            if not self.glibc_aio_runtime_available():
                self.failures.append(
                    "glibc-all-in-one v2 runtime verification failed: "
                    "command or Python dependencies unavailable"
                )
                return

        if self.update_existing or not index_ready:
            self.info("glibc-all-in-one: updating the libc package index")
            update_list = self.run(
                [str(GLIBC_AIO_COMMAND), "mirror", "update"],
                cwd=HOME,
                check=False,
                network=True,
                timeout=300,
            )
            if update_list.returncode != 0 or not self.glibc_aio_index_available():
                self.failures.append("glibc-all-in-one libc index update failed")
                return

        if not self.configure_glibc_library():
            return
        self.ok(
            f"glibc-aio and compact glibc library configured "
            f"({GLIBC_AIO_COMMAND}; {GLIBC_LIBRARY_ROOT})"
        )

    def glibc_aio_latest_packages(self) -> 'dict[tuple[str, str], str]':
        libc_list = GLIBC_AIO_DIR / "list"
        try:
            lines = libc_list.read_text(encoding="utf-8").splitlines()
        except OSError:
            return {}

        latest: dict[tuple[str, str], str] = {}
        arches = "|".join(re.escape(arch) for arch in GLIBC_LIBRARY_ARCHES)
        pattern = re.compile(
            rf"^(?P<version>\\d+\\.\\d+)-.+_(?P<arch>{arches})$"
        )
        for raw in lines:
            package = raw.strip()
            match = pattern.fullmatch(package)
            if match is None:
                continue
            key = (match.group("version"), match.group("arch"))
            current = latest.get(key)
            if current is None:
                latest[key] = package
                continue
            candidate_version = package.rsplit("_", 1)[0]
            current_version = current.rsplit("_", 1)[0]
            newer = self.run(
                [
                    "dpkg", "--compare-versions",
                    candidate_version, "gt", current_version,
                ],
                check=False,
                capture=True,
                timeout=30,
            )
            if newer.returncode == 0:
                latest[key] = package
        return latest

    @staticmethod
    def glibc_package_sort_key(item: 'tuple[tuple[str, str], str]') -> 'tuple[tuple[int, ...], str]':
        (version, arch), _package = item
        return tuple(int(part) for part in version.split(".")), arch

    def configure_glibc_library(self) -> bool:
        packages = self.glibc_aio_latest_packages()
        if not packages:
            self.failures.append(
                "glibc library configuration failed: no amd64/i386 packages in the index"
            )
            return False

        for (version, arch), package in sorted(
            packages.items(), key=self.glibc_package_sort_key
        ):
            target = GLIBC_AIO_DIR / "libs" / package
            if not target.is_dir():
                self.info(f"glibc {version} {arch}: downloading {package}")
                download = self.run(
                    [str(GLIBC_AIO_COMMAND), "download", package, "--no-dbg"],
                    cwd=HOME,
                    check=False,
                    network=True,
                    timeout=600,
                )
                if download.returncode != 0 or not target.is_dir():
                    self.failures.append(f"glibc download failed: {package}")
                    return False

            version_dir = GLIBC_LIBRARY_ROOT / version
            create_dir = self.run(
                ["mkdir", "-p", str(version_dir)],
                sudo=True,
                check=False,
            )
            if create_dir.returncode != 0:
                self.failures.append(f"glibc library directory creation failed: {version_dir}")
                return False

            link = version_dir / arch
            if (link.exists() or link.is_symlink()) and not link.is_symlink():
                self.failures.append(
                    f"glibc library path exists and is not a symlink: {link}"
                )
                return False
            try:
                current_target = link.resolve(strict=False) if link.is_symlink() else None
                wanted_target = target.resolve(strict=False)
            except OSError:
                current_target = None
                wanted_target = target
            if current_target == wanted_target:
                continue

            create_link = self.run(
                ["ln", "-sfn", str(target), str(link)],
                sudo=True,
                check=False,
            )
            if create_link.returncode != 0:
                self.failures.append(f"glibc library link failed: {link}")
                return False
        return True

    def glibc_library_available(self) -> bool:
        packages = self.glibc_aio_latest_packages()
        if not packages:
            return False
        for (version, arch), package in packages.items():
            target = GLIBC_AIO_DIR / "libs" / package
            link = GLIBC_LIBRARY_ROOT / version / arch
            if not target.is_dir() or not link.is_symlink():
                return False
            try:
                if link.resolve(strict=True) != target.resolve(strict=True):
                    return False
            except OSError:
                return False
        return True

'''
text = text[:start] + new_block + text[end:]

verify_old = '''        if self.glibc_aio_runtime_available() and self.glibc_aio_index_available():
            self.ok(f"glibc-aio: {GLIBC_AIO_COMMAND} (runtime, dependencies and index ready)")
        else:
            ok_all = False
            message = "verification failed: glibc-aio runtime, dependencies or index unavailable"
            if message not in self.failures:
                self.failures.append(message)
            self.error(message)

        return ok_all
'''
verify_new = '''        if self.glibc_aio_runtime_available() and self.glibc_aio_index_available():
            self.ok(f"glibc-aio: {GLIBC_AIO_COMMAND} (runtime, dependencies and index ready)")
        else:
            ok_all = False
            message = "verification failed: glibc-aio runtime, dependencies or index unavailable"
            if message not in self.failures:
                self.failures.append(message)
            self.error(message)

        if self.glibc_library_available():
            self.ok(
                f"glibc library: {GLIBC_LIBRARY_ROOT} "
                "(latest amd64/i386 packages linked)"
            )
        else:
            ok_all = False
            message = "verification failed: compact /glibc library unavailable"
            if message not in self.failures:
                self.failures.append(message)
            self.error(message)

        return ok_all
'''
if verify_old not in text:
    raise SystemExit("glibc verify anchor not found")
text = text.replace(verify_old, verify_new, 1)
path.write_text(text, encoding="utf-8")

# Add focused unit tests without touching the existing test structure.
test_path = Path("tests/test_init.py")
tests = test_path.read_text(encoding="utf-8")
marker = "\n\nif __name__ == \"__main__\":\n"
if marker not in tests:
    raise SystemExit("test file footer not found")
if "test_glibc_latest_packages_selects_latest_revision_per_arch" not in tests:
    new_tests = r'''
    def test_glibc_latest_packages_selects_latest_revision_per_arch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            aio = root / "glibc-all-in-one"
            aio.mkdir()
            (aio / "list").write_text(
                "2.35-0ubuntu3_amd64\n"
                "2.35-0ubuntu3.15_amd64\n"
                "2.35-0ubuntu3_i386\n"
                "2.35-0ubuntu3.15_i386\n"
                "2.39-0ubuntu8.9_amd64\n"
                "2.39-0ubuntu8.9_i386\n"
                "2.39-0ubuntu8.9_arm64\n",
                encoding="utf-8",
            )
            real_run = self.bootstrap.run
            with mock.patch.object(MODULE, "GLIBC_AIO_DIR", aio):
                self.bootstrap.run = mock.Mock(side_effect=real_run)
                latest = self.bootstrap.glibc_aio_latest_packages()
            self.assertEqual(latest[("2.35", "amd64")], "2.35-0ubuntu3.15_amd64")
            self.assertEqual(latest[("2.35", "i386")], "2.35-0ubuntu3.15_i386")
            self.assertEqual(latest[("2.39", "amd64")], "2.39-0ubuntu8.9_amd64")
            self.assertNotIn(("2.39", "arm64"), latest)

    def test_glibc_library_reuses_downloads_and_creates_compact_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            aio = root / "glibc-all-in-one"
            library = root / "glibc"
            package = "2.35-0ubuntu3.15_amd64"
            target = aio / "libs" / package
            target.mkdir(parents=True)
            self.bootstrap.glibc_aio_latest_packages = mock.Mock(
                return_value={("2.35", "amd64"): package}
            )

            def fake_run(command, **kwargs):
                if command[:2] == ["mkdir", "-p"]:
                    Path(command[2]).mkdir(parents=True, exist_ok=True)
                elif command[:2] == ["ln", "-sfn"]:
                    link = Path(command[3])
                    if link.exists() or link.is_symlink():
                        link.unlink()
                    link.symlink_to(command[2])
                elif "download" in command:
                    self.fail("existing libc must not be downloaded again")
                return subprocess.CompletedProcess(command, 0, "", "")

            self.bootstrap.run = mock.Mock(side_effect=fake_run)
            with (
                mock.patch.object(MODULE, "GLIBC_AIO_DIR", aio),
                mock.patch.object(MODULE, "GLIBC_LIBRARY_ROOT", library),
            ):
                self.assertTrue(self.bootstrap.configure_glibc_library())
                link = library / "2.35" / "amd64"
                self.assertTrue(link.is_symlink())
                self.assertEqual(link.resolve(), target.resolve())
                self.assertTrue(self.bootstrap.glibc_library_available())
'''
    tests = tests.replace(marker, "\n" + new_tests + marker, 1)
    test_path.write_text(tests, encoding="utf-8")
