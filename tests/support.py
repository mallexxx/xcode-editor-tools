import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from editor_tools.bootstrap import apply, save_config
from editor_tools.repository import Repository
from runtime.editor_support import normalize_config

SOURCE = Path(__file__).resolve().parents[1]


class RepositoryTest(unittest.TestCase):
    def setUp(self):
        isolation = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        isolation.start()
        self.addCleanup(isolation.stop)
        self.temporary = tempfile.TemporaryDirectory(prefix="editor-tools-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "Orbit project with spaces"
        self.root.mkdir()
        self.git("init", "--quiet", "--initial-branch=main")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        container = self.root / "Orbit.xcworkspace"
        container.mkdir()
        (container / "contents.xcworkspacedata").write_text('<?xml version="1.0"?><Workspace version="1.0"></Workspace>\n')
        (self.root / "README").write_text("Synthetic test repository\n")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "Synthetic fixture")
        self.repository = Repository(self.root)
        self.config = normalize_config({
            "container": "Orbit.xcworkspace", "profiles": {
                "macos": {"scheme": "Orbit App", "app_path": "Debug/Orbit.app", "test_scheme": "Orbit Tests"},
                "ios": {"scheme": "Orbit iOS", "app_path": "Debug-iphonesimulator/Orbit.app"},
            }, "default_platform": "macos",
        })
        save_config(self.repository, self.config)

    def git(self, *arguments, root=None, check=True):
        environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        # Keep machine-level hooks and signing settings out of synthetic fixtures.
        environment.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        return subprocess.run(["git", "-C", str(root or self.root), *arguments],
                              capture_output=True, text=True, check=check, env=environment)

    def populate(self, **kwargs):
        return apply(self.repository, self.root, self.config, **kwargs)

    def read_json(self, relative):
        return json.loads((self.root / relative).read_text())

    def hook(self, directory, name="post-checkout", status=0):
        directory.mkdir(parents=True, exist_ok=True)
        marker = self.base / (name + "-called")
        file = directory / name
        file.write_text("#!/usr/bin/env python3\nimport pathlib,sys\n" +
                        f"pathlib.Path({str(marker)!r}).write_text(repr(sys.argv[1:]))\n" +
                        f"raise SystemExit({status})\n")
        file.chmod(0o755)
        return file, marker
