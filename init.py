#!/usr/bin/env python3
"""Set up the distribution's Python and common libraries with APT."""
import os
from pathlib import Path
import re
import subprocess
import sys


PYTHON = "/usr/bin/python3"
PYTHON_ALIAS = "python-is-python3"
LIBRARIES = {
    "python3-pip": "pip",
    "python3-setuptools": "setuptools",
    "python3-wheel": "wheel",
    "python3-ipython": "IPython",
    "python3-magic": "magic",
    "python3-pil": "PIL",
    "python3-requests": "requests",
    "python3-sympy": "sympy",
    "python3-yaml": "yaml",
}
PACKAGES = ("python3", "python3-dev", *LIBRARIES)
OLD_ACTIVATION = re.compile(
    rb"^# >>> init Python tools >>>\r?\n.*?^# <<< init Python tools <<<(?:\r?\n|\Z)",
    re.MULTILINE | re.DOTALL,
)


def missing_packages():
    result = subprocess.run(
        ["dpkg-query", "-W", "-f=${db:Status-Status}\t${Package}\n", *PACKAGES, PYTHON_ALIAS],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        universal_newlines=True,
    )
    installed = {line.split("\t", 1)[1] for line in result.stdout.splitlines() if line.startswith("installed\t")}
    return [package for package in PACKAGES if package not in installed], PYTHON_ALIAS not in installed


def alias_available():
    result = subprocess.run(
        ["apt-cache", "--no-all-versions", "show", PYTHON_ALIAS],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def install_packages():
    missing, alias_missing = missing_packages()
    if not missing and not (alias_missing and alias_available()):
        print("System Python packages are already installed.")
        return

    apt = ["sudo"] if os.geteuid() else []
    apt += ["apt-get", "-o", "Acquire::Retries=2"]
    subprocess.run([*apt, "update"], check=True)
    if alias_missing and alias_available():
        missing.append(PYTHON_ALIAS)
    if missing:
        subprocess.run([*apt, "install", "-y", "--no-install-recommends", *missing], check=True)


def remove_old_activation(home):
    for filename in (".bashrc", ".zshrc"):
        profile = home / filename
        try:
            content = profile.read_bytes()
        except FileNotFoundError:
            continue
        updated = OLD_ACTIVATION.sub(b"", content)
        if updated != content:
            profile.write_bytes(updated)
            print("Removed old Python activation from {}.".format(profile))


def main(args):
    if args:
        print("Usage: python3 init.py", file=sys.stderr)
        return 2

    try:
        install_packages()
        subprocess.run([PYTHON, "-I", "-c", "import " + ", ".join(LIBRARIES.values())], check=True)
        remove_old_activation(Path.home())
    except (OSError, subprocess.CalledProcessError) as error:
        print("System Python setup failed: {}".format(error), file=sys.stderr)
        return 1

    print("System Python is ready at {}.".format(PYTHON))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
