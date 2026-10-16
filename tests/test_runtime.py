import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
from unittest import mock

from editor_tools.bootstrap import apply, save_config
from editor_tools.repository import Repository
from editor_tools import hooks
from runtime.editor_support import derived_data, normalize_config, render_bsp, xcode_hash
from runtime.manage_background import agent
from runtime.install_server import install as install_server
from support import RepositoryTest, SOURCE


class RuntimeTests(RepositoryTest):
    def setUp(self):
        super().setUp()
        self.bin = self.base / "fake commands"
        self.bin.mkdir()
        self.capture = self.base / "arguments.json"
        self.environment = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"], CAPTURE_ARGS=str(self.capture))
        self.fake("xcodebuild", "import json,os,sys\nfrom pathlib import Path\n"
                  "Path(os.environ['CAPTURE_ARGS']).write_text(json.dumps(sys.argv[1:]))\n"
                  "print('BUILD SUCCEEDED')\nraise SystemExit(int(os.environ.get('FAKE_BUILD_STATUS','0')))\n")
        self.fake("xcbeautify", "import sys\nsys.stdout.write(sys.stdin.read())\n")
        self.populate()

    def fake(self, name, content):
        path = self.bin / name
        path.write_text("#!/usr/bin/env python3\n" + content)
        path.chmod(0o755)
        return path

    def run_script(self, name, *arguments, environment=None):
        return subprocess.run([str(self.root / self.config["scripts_dir"] / name), *arguments],
                              cwd=self.base, env=environment or self.environment, capture_output=True, text=True)

    def test_regular_build_preserves_xcode_parameters_and_debug_paths(self):
        result = self.run_script("xcodebuild.sh", "build", "Orbit App")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = json.loads(self.capture.read_text())
        self.assertEqual(args[:6], ["-workspace", str(self.root / "Orbit.xcworkspace"), "-scheme", "Orbit App", "-configuration", "Debug"])
        self.assertNotIn("-derivedDataPath", args)
        self.assertEqual(args[-1], "build")
        self.assertIn("no source map", (self.root / ".build/debug.lldbinit").read_text())
        self.assertEqual((self.root / ".build/products").readlink(), derived_data(self.root, self.config) / "Build/Products")

    def test_macos_private_temporary_paths_use_foundation_spelling(self):
        if sys.platform != "darwin" or not str(self.root).startswith("/private/"):
            self.skipTest("macOS temporary-path aliases")
        alias = Path(str(self.root / self.config["container"])[len("/private"):])
        self.assertTrue(alias.samefile(self.root / self.config["container"]))
        self.assertEqual(derived_data(self.root, self.config).name, "Orbit-" + xcode_hash(alias))

    def test_project_and_configuration_are_configurable(self):
        (self.root / "Orbit.xcodeproj").mkdir()
        self.config.update(container="Orbit.xcodeproj", configuration="Development")
        save_config(self.repository, self.config)
        self.populate()
        result = self.run_script("xcodebuild.sh", "build", "Orbit App", "macOS", "-showBuildSettings")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = json.loads(self.capture.read_text())
        self.assertEqual(args[:2], ["-project", str(self.root / "Orbit.xcodeproj")])
        self.assertEqual(args[args.index("-configuration") + 1], "Development")
        self.assertIn("-showBuildSettings", args)

    def test_build_failure_status_is_preserved_through_formatter(self):
        environment = {**self.environment, "FAKE_BUILD_STATUS": "9"}
        result = self.run_script("xcodebuild.sh", "build", "Orbit App", environment=environment)
        self.assertEqual(result.returncode, 9, result.stderr)

    def test_cache_mode_maps_sources_and_uses_local_derived_data(self):
        environment = {**self.environment, "XCODE_EDITOR_WORKTREE_CACHE": "1"}
        result = self.run_script("xcodebuild.sh", "build", "Orbit App", environment=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        args = json.loads(self.capture.read_text())
        self.assertEqual(args[args.index("-derivedDataPath") + 1], str(self.root / ".build/xcodebuild"))
        self.assertIn("COMPILATION_CACHE_ENABLE_CACHING=YES", args)
        settings = (self.root / ".build/debug.lldbinit").read_text()
        self.assertIn('"/^wt"', settings)
        self.assertIn(json.dumps(str(self.root)), settings)

    def test_legacy_environment_name_is_private_configuration(self):
        self.config["compatibility"]["worktree_cache_environment"] = "EXAMPLE_LEGACY_CACHE"
        save_config(self.repository, self.config)
        self.populate()
        result = self.run_script("xcodebuild.sh", "build", "Orbit App", environment={**self.environment, "EXAMPLE_LEGACY_CACHE": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("-derivedDataPath", json.loads(self.capture.read_text()))

    def test_argument_paths_with_apostrophes_are_not_shell_evaluated(self):
        renamed = self.base / "Orbit's $data project"
        self.root.rename(renamed)
        self.root = renamed
        self.repository = Repository(renamed)
        self.populate()
        result = self.run_script("xcodebuild.sh", "build", "Orbit App", environment={**self.environment, "XCODE_EDITOR_WORKTREE_CACHE": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(renamed / "Orbit.xcworkspace"), json.loads(self.capture.read_text()))
        self.assertIn(json.dumps(str(renamed)), (renamed / ".build/debug.lldbinit").read_text())
        launch = self.read_json("Orbit.code-workspace")["launch"]["configurations"][0]
        self.assertEqual(launch["initCommands"], ["command source -s 1 -e 0 " + json.dumps(str(renamed / ".build/debug.lldbinit"))])

    def test_ios_tests_select_a_concrete_simulator(self):
        self.fake("xcrun", "import json\nprint(json.dumps({'devices':{'runtime':[{'name':'iPhone Example','udid':'fixture-udid','state':'Booted'}]}}))\n")
        self.config["profiles"]["ios"].update(test_scheme="Orbit iOS Tests", test_target="OrbitTests")
        self.populate()
        result = self.run_script("simulator.sh", "--test", "Orbit iOS Tests", "--only-testing", "OrbitTests/TestExample")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = json.loads(self.capture.read_text())
        self.assertIn("platform=iOS Simulator,id=fixture-udid", args)
        self.assertIn("-only-testing:OrbitTests/TestExample", args)
        self.assertEqual(args[-1], "test")
        tasks = self.read_json("Orbit.code-workspace")["tasks"]["tasks"]
        task = next(t for t in tasks if t["label"] == "Test Orbit iOS Tests")
        self.assertTrue(task["command"].endswith("simulator.sh"))
        result = self.run_script("simulator.sh", "--test", "Orbit iOS Tests")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(a.startswith("-only-testing:") for a in json.loads(self.capture.read_text())))

    def test_launcher_uses_runtime_root_and_explicit_server(self):
        server = self.fake("fake-sourcekit-server", "import json,os,sys\nfrom pathlib import Path\n"
                           "Path(os.environ['CAPTURE_ARGS']).write_text(json.dumps({'argv':sys.argv[1:],'cwd':os.getcwd()}))\n")
        result = self.run_script("sourcekit-xcode-bsp.sh", environment={**self.environment, "SOURCEKIT_XCODE_BSP": str(server)})
        self.assertEqual(result.returncode, 0, result.stderr)
        captured = json.loads(self.capture.read_text())
        self.assertEqual(captured, {"argv": ["serve"], "cwd": str(self.root)})

    def test_platform_setup_runs_without_the_source_harness(self):
        server = self.fake("fake-sourcekit-server", "raise SystemExit(0)\n")
        result = self.run_script("setup-build-server.py", "ios", environment={**self.environment, "SOURCEKIT_XCODE_BSP": str(server)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read_json("buildServer.json")["platform"], "iphonesimulator")
        result = self.run_script("setup-build-server.py", environment={**self.environment, "SOURCEKIT_XCODE_BSP": str(server)})
        self.assertIn("up to date", result.stdout)

    def test_preserved_scripts_can_import_the_original_derived_data_helper(self):
        code = "from xcode_derived_data import derived_data; import sys; print(derived_data(sys.argv[1]))"
        result = subprocess.run([sys.executable, "-c", code, str(self.root)],
                                cwd=self.root / "scripts/vscode", capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(derived_data(self.root, self.config)))

    def test_background_agent_escapes_paths_and_uses_configured_scripts(self):
        value = agent(self.root, self.config)
        decoded = plistlib.loads(plistlib.dumps(value))
        self.assertEqual(decoded["ProgramArguments"][1], str(self.root / "scripts/vscode/index-in-background.py"))
        self.assertEqual(decoded["StartInterval"], 1800)
        self.assertTrue(decoded["Label"].startswith("local.xcode-editor."))

    def test_help_does_not_start_a_build(self):
        for name in ("xcodebuild.sh", "sourcekit-xcode-bsp.sh", "simulator.sh"):
            result = self.run_script(name, "--help")
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.capture.exists())

    def test_shell_files_have_valid_syntax(self):
        for file in (SOURCE / "runtime").glob("*.sh"):
            result = subprocess.run(["bash", "-n", str(file)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_installer_pin_is_not_a_floating_branch(self):
        self.config["build_server"]["revision"] = "main"
        with self.assertRaises(ValueError):
            normalize_config(self.config)

    def test_installer_refuses_unrelated_directories_and_symlinks_before_building(self):
        target = self.base / "unrelated data"
        target.mkdir()
        file = target / "important.txt"
        file.write_text("keep me")
        link = self.base / "linked installation"
        link.symlink_to(target, target_is_directory=True)
        with mock.patch("runtime.install_server.subprocess.run") as run:
            for path in (target, link):
                self.config["build_server"]["install_dir"] = str(path)
                with self.assertRaises(ValueError):
                    install_server(self.config)
            run.assert_not_called()
        self.assertEqual(file.read_text(), "keep me")

    def test_harness_can_run_from_an_unrelated_source_location(self):
        clone = self.base / "renamed source tools"
        clone.mkdir()
        for directory in ("editor_tools", "runtime"):
            shutil.copytree(SOURCE / directory, clone / directory, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(SOURCE / "xcode_editor.py", clone / "xcode_editor.py")
        hooks.install(self.repository, clone / "xcode_editor.py")
        linked = self.base / "outside linked checkout"
        self.git("worktree", "add", "--detach", str(linked), "HEAD")
        self.assertTrue((linked / "buildServer.json").is_file())


class IndexerTests(RepositoryTest):
    def setUp(self):
        super().setUp()
        sys.path.insert(0, str(SOURCE / "runtime"))
        self.addCleanup(sys.path.remove, str(SOURCE / "runtime"))
        spec = importlib.util.spec_from_file_location("example_indexer", SOURCE / "runtime/index-in-background.py")
        self.indexer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.indexer)
        self.populate()

    def test_platform_change_invalidates_indexed_state(self):
        before = self.indexer.worktree_state(str(self.root))
        (self.root / "buildServer.json").write_text(json.dumps(render_bsp(self.root, self.config, "ios")))
        self.assertNotEqual(before, self.indexer.worktree_state(str(self.root)))

    def test_all_worktrees_handles_spaces_and_filters_bare_root(self):
        self.assertEqual(self.indexer.configured_worktrees(str(self.root)), [str(self.root)])

    def test_live_pid_does_not_accept_a_reused_unrelated_process(self):
        path = self.base / "pid"
        path.write_text(str(os.getpid()))
        with mock.patch.object(self.indexer.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "ordinary-process")):
            self.assertIsNone(self.indexer.live_pid(path))
