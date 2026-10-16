"""Opt-in smoke test against a real, unrelated macOS Xcode application."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from editor_tools.bootstrap import apply, save_config
from editor_tools.cli import initial_config
from editor_tools.repository import Repository
from support import SOURCE


@unittest.skipUnless(os.environ.get("XCODE_EDITOR_RUN_XCODE_TESTS") == "1", "set XCODE_EDITOR_RUN_XCODE_TESTS=1 for a real Xcode build")
class RealXcodeTests(unittest.TestCase):
    def test_unrelated_project_build_and_regular_derived_data(self):
        self.assertIsNotNone(shutil.which("xcodegen"), "Install xcodegen for this optional test")
        with tempfile.TemporaryDirectory(prefix="editor-xcode-smoke-") as directory:
            root = Path(directory).resolve() / "Orbit sample checkout"
            shutil.copytree(SOURCE / "tests/fixtures/OrbitSample", root)
            subprocess.run(["xcodegen", "generate"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
            repository = Repository(root)
            config = initial_config(root, scheme="OrbitSample", app="OrbitSample")
            save_config(repository, config)
            apply(repository, root, config)
            result = subprocess.run([str(root / "scripts/vscode/xcodebuild.sh"), "build", "OrbitSample"],
                                    cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            executable = root / ".build/products/Debug/OrbitSample.app/Contents/MacOS/OrbitSample"
            self.assertTrue(executable.is_file(), f"Product link: {(root / '.build/products').readlink()}\n" + result.stdout + result.stderr)
            self.assertEqual(subprocess.check_output([str(executable)], text=True).strip(), "Orbit sample")
            bsp = json.loads((root / "buildServer.json").read_text())
            self.assertEqual(bsp["workspace"], str(root / "OrbitSample.xcodeproj"))
            if os.environ.get("SOURCEKIT_XCODE_BSP"):
                targets = subprocess.run([os.environ["SOURCEKIT_XCODE_BSP"], "list-targets"], cwd=root, capture_output=True, text=True)
                self.assertEqual(targets.returncode, 0, targets.stdout + targets.stderr)
                self.assertIn("OrbitSample", targets.stdout)
