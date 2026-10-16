#!/usr/bin/env python3
"""Manage optional headless indexing through a per-repository launchd agent."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys

try:
    from .editor_support import atomic_write, background_label, find_root, load_worktree_config
except ImportError:
    from editor_support import atomic_write, background_label, find_root, load_worktree_config


def agent(root, config):
    label = background_label(root, config)
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_" for character in label):
        raise ValueError("background_label contains characters invalid for a launchd job name")
    log = str(Path.home() / "Library/Logs" / (label + ".log"))
    return {
        "Label": label,
        "ProgramArguments": [sys.executable, str(Path(root) / config["scripts_dir"] / "index-in-background.py"),
                             "--all", "--if-idle", str(root)],
        "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        "StartInterval": 1800, "LowPriorityIO": True, "Nice": 10,
        "StandardOutPath": log, "StandardErrorPath": log,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "uninstall", "status"])
    args = parser.parse_args()
    root = find_root()
    config = load_worktree_config(root)
    value = agent(root, config)
    label = value["Label"]
    target = f"gui/{os.getuid()}"
    path = Path.home() / "Library/LaunchAgents" / (label + ".plist")
    if args.action == "status":
        return subprocess.run(["launchctl", "print", target + "/" + label]).returncode
    subprocess.run(["launchctl", "bootout", target + "/" + label], capture_output=True)
    if args.action == "install":
        if path.is_symlink():
            raise ValueError("Refusing to replace a symlinked launch agent")
        atomic_write(path, plistlib.dumps(value))
        subprocess.run(["launchctl", "bootstrap", target, str(path)], check=True)
        print(f"Installed {label}; log: {value['StandardOutPath']}")
    else:
        path.unlink(missing_ok=True)
        print(f"Uninstalled {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
