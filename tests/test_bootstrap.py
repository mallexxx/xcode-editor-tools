import hashlib
import json
import os
from pathlib import Path
import subprocess

from editor_tools import hooks
from editor_tools.bootstrap import apply, save_config
from editor_tools.cli import initial_config
from editor_tools.repository import Repository
from runtime.editor_support import PROFILE_PATH, current_platform, normalize_config, render_bsp
from support import RepositoryTest, SOURCE


class BootstrapTests(RepositoryTest):
    def test_generates_ignored_self_contained_files_and_correct_paths(self):
        result = self.populate()
        self.assertGreater(len(result["written"]), 10)
        self.assertEqual(self.git("status", "--porcelain").stdout, "")
        bsp = self.read_json("buildServer.json")
        self.assertEqual(bsp["workspace"], str(self.root / "Orbit.xcworkspace"))
        self.assertEqual(bsp["argv"], [str(self.root / "scripts/vscode/sourcekit-xcode-bsp.sh")])
        self.assertEqual(bsp["configuration"], "Debug")
        for file in result["written"]:
            self.assertEqual(self.git("check-ignore", "-q", file, check=False).returncode, 0, file)
        self.assertEqual(self.read_json(PROFILE_PATH)["container"], "Orbit.xcworkspace")

    def test_reapply_does_not_rewrite_discovery_or_custom_settings(self):
        self.populate()
        stamp = (self.root / "buildServer.json").stat().st_mtime_ns
        settings = self.root / ".vscode/settings.json"
        settings.write_text('{"editor.fontSize": 19}\n')
        result = self.populate()
        self.assertEqual((self.root / "buildServer.json").stat().st_mtime_ns, stamp)
        self.assertEqual(json.loads(settings.read_text()), {"editor.fontSize": 19})
        self.assertIn(".vscode/settings.json", result["preserved"])

    def test_tracked_editor_and_discovery_files_are_preserved(self):
        directory = self.root / ".vscode"
        directory.mkdir()
        (directory / "settings.json").write_text('{"editor.fontSize": 23}\n')
        (self.root / "buildServer.json").write_text('{"name":"other-server"}\n')
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "Tracked fixture preferences")
        self.populate()
        self.assertEqual(self.read_json("buildServer.json"), {"name": "other-server"})
        self.assertEqual(self.git("diff", "--exit-code").returncode, 0)

    def test_ios_selection_survives_backfill(self):
        self.populate()
        (self.root / "buildServer.json").write_text(json.dumps(render_bsp(self.root, self.config, "ios")))
        self.populate()
        self.assertEqual(self.read_json("buildServer.json")["platform"], "iphonesimulator")

    def test_custom_script_location_and_container_name(self):
        self.config["scripts_dir"] = "tools/editor integration"
        self.config["workspace_file"] = "Editor.code-workspace"
        self.populate()
        workspace = self.read_json("Editor.code-workspace")
        self.assertEqual(workspace["tasks"]["tasks"][0]["command"], "${workspaceFolder}/tools/editor integration/setup-build-server.py")
        self.assertTrue((self.root / "tools/editor integration/editor_support.py").is_file())

    def test_ignore_rules_treat_path_metacharacters_literally(self):
        self.config["scripts_dir"] = "tools/editor[local]"
        self.config["workspace_file"] = "Editor[local].code-workspace"
        result = self.populate()
        for file in result["written"]:
            self.assertEqual(self.git("check-ignore", "-q", file, check=False).returncode, 0, file)

    def test_project_container(self):
        (self.root / "Nova.xcodeproj").mkdir()
        self.config["container"] = "Nova.xcodeproj"
        self.config["workspace_file"] = "Nova.code-workspace"
        self.populate()
        self.assertEqual(self.read_json("buildServer.json")["workspace"], str(self.root / "Nova.xcodeproj"))

    def test_discovery_prefers_workspace_and_rejects_ambiguity(self):
        (self.root / "Nova.xcodeproj").mkdir()
        self.assertEqual(initial_config(self.root)["container"], "Orbit.xcworkspace")
        (self.root / "Other.xcworkspace").mkdir()
        with self.assertRaises(ValueError):
            initial_config(self.root)

    def test_paths_cannot_escape_or_write_git_data(self):
        for value in ("../outside", "/absolute", ".git/hooks", ".", "line\nbreak"):
            config = {**self.config, "scripts_dir": value}
            with self.assertRaises(ValueError, msg=value):
                normalize_config(config)

    def test_dry_run_does_not_write_files_or_excludes(self):
        excludes = self.repository.common / "info/exclude"
        before = excludes.read_bytes()
        result = self.populate(dry_run=True)
        self.assertTrue(result["written"])
        self.assertFalse((self.root / "buildServer.json").exists())
        self.assertEqual(before, excludes.read_bytes())

    def test_symlinked_state_is_rejected(self):
        outside = self.base / "external"
        outside.mkdir()
        (self.root / ".build").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.populate()
        self.assertEqual(list(outside.iterdir()), [])

    def test_symlinked_script_directory_is_not_followed(self):
        outside = self.base / "external scripts"
        outside.mkdir()
        (self.root / "scripts").mkdir()
        (self.root / "scripts/vscode").symlink_to(outside, target_is_directory=True)
        result = self.populate()
        self.assertIn("scripts/vscode/xcodebuild.sh", result["preserved"])
        self.assertEqual(list(outside.iterdir()), [])

    def test_foreign_repository_rejected(self):
        other = self.base / "other"
        other.mkdir()
        self.git("init", "--quiet", root=other)
        with self.assertRaises(ValueError):
            apply(self.repository, other, self.config)

    def test_incomplete_checkout_is_reported(self):
        self.config["container"] = "NotYetCheckedOut.xcworkspace"
        result = self.populate()
        self.assertIn("container missing", result["skipped"])

    def test_existing_ownership_manifest_is_adopted(self):
        self.config["state_manifest"] = ".build/legacy/files.json"
        target = self.root / "scripts/vscode/xcodebuild.sh"
        target.parent.mkdir(parents=True)
        target.write_text("older owned wrapper\n")
        stamp = self.root / self.config["state_manifest"]
        stamp.parent.mkdir(parents=True)
        stamp.write_text(json.dumps({"scripts/vscode/xcodebuild.sh": hashlib.sha256(target.read_bytes()).hexdigest()}))
        self.populate()
        self.assertIn("container_flag", target.read_text())

    def test_target_exclusions_follow_each_worktrees_package_directories(self):
        package = self.root / "OtherPlatform/Packages/SideKit"
        package.mkdir(parents=True)
        (package / "Package.swift").write_text("// fixture\n")
        profile = self.config["profiles"]["macos"]
        profile.update(targets={"include": ["^Orbit/"], "exclude": ["Store"]},
                       exclude_projects=["Other.App"], exclude_package_directories=["OtherPlatform/Packages"])
        self.populate()
        self.assertEqual(self.read_json("buildServer.json")["targets"]["exclude"], [r"^(Other\.App|SideKit)/", "Store"])


class HookTests(RepositoryTest):
    def test_default_hooks_and_outside_worktree_bootstrap(self):
        target = hooks.install(self.repository, SOURCE / "xcode_editor.py")
        self.assertTrue((target / "post-checkout").is_file())
        outside = self.base / "different directory" / "linked worktree"
        self.git("worktree", "add", "--detach", str(outside), "HEAD")
        self.assertTrue((outside / "buildServer.json").is_file())
        self.assertEqual(self.git("status", "--porcelain", root=outside).stdout, "")
        hooks.uninstall(self.repository)
        self.assertIsNone(self.repository.local_hooks_path())

    def test_existing_hook_arguments_status_and_uninstall(self):
        original, marker = self.hook(self.repository.common / "hooks", status=7)
        before = original.read_bytes()
        target = hooks.install(self.repository, SOURCE / "xcode_editor.py")
        result = self.git("checkout", "--detach", "HEAD", check=False)
        self.assertNotEqual(result.returncode, 0)
        direct = subprocess.run([str(target / "post-checkout"), "old", "new", "1"], cwd=self.root, capture_output=True)
        self.assertEqual(direct.returncode, 7, direct.stderr.decode())
        self.assertTrue(marker.is_file())
        self.assertIn("'1'", marker.read_text())
        self.assertTrue((self.root / "buildServer.json").is_file())
        hooks.uninstall(self.repository)
        self.assertEqual(original.read_bytes(), before)

    def test_absolute_custom_hooks_are_chained(self):
        directory = self.base / "shared hooks"
        _, marker = self.hook(directory)
        self.git("config", "core.hooksPath", str(directory))
        hooks.install(self.repository, SOURCE / "xcode_editor.py")
        self.git("checkout", "--detach", "HEAD")
        self.assertTrue(marker.is_file())
        hooks.uninstall(self.repository)
        self.assertEqual(self.repository.effective_hooks_path(), str(directory))

    def test_relative_hooks_use_the_new_worktree(self):
        directory = self.root / ".githooks"
        _, marker = self.hook(directory)
        self.git("add", ".githooks")
        self.git("commit", "--quiet", "-m", "Fixture hook")
        self.git("config", "core.hooksPath", ".githooks")
        hooks.install(self.repository, SOURCE / "xcode_editor.py")
        outside = self.base / "second worktree"
        self.git("worktree", "add", "--detach", str(outside), "HEAD")
        self.assertTrue(marker.is_file())
        self.assertTrue((outside / "buildServer.json").is_file())
        hooks.uninstall(self.repository)
        self.assertEqual(self.repository.effective_hooks_path(), ".githooks")

    def test_adopted_old_hook_is_skipped_only_at_the_expected_hash(self):
        original, marker = self.hook(self.repository.common / "hooks")
        digest = hashlib.sha256(original.read_bytes()).hexdigest()
        hooks.install(self.repository, SOURCE / "xcode_editor.py", digest)
        self.git("checkout", "--detach", "HEAD")
        self.assertFalse(marker.exists())
        self.assertTrue((self.root / "buildServer.json").is_file())

    def test_wrong_adoption_hash_does_not_change_hooks_configuration(self):
        self.hook(self.repository.common / "hooks")
        with self.assertRaises(ValueError):
            hooks.install(self.repository, SOURCE / "xcode_editor.py", "0" * 64)
        self.assertIsNone(self.repository.effective_hooks_path())

    def test_uninstall_preserves_a_later_user_hooks_setting(self):
        hooks.install(self.repository, SOURCE / "xcode_editor.py")
        self.git("config", "core.hooksPath", "user-changed-hooks")
        with self.assertRaises(ValueError):
            hooks.uninstall(self.repository)
        self.assertEqual(self.repository.effective_hooks_path(), "user-changed-hooks")

    def test_reinstall_updates_entry_point_without_chaining_itself(self):
        hooks.install(self.repository, SOURCE / "xcode_editor.py")
        hooks.install(self.repository, SOURCE / "xcode_editor.py")
        state = json.loads((self.repository.state / "installation.json").read_text())
        self.assertIsNone(state["previous_effective_hooks_path"])

    def test_absent_override_hooks_are_not_created(self):
        target = hooks.install(self.repository, SOURCE / "xcode_editor.py")
        self.assertFalse((target / "push-to-checkout").exists())
        self.assertFalse((target / "proc-receive").exists())

    def test_target_repository_can_move_and_be_reinstalled(self):
        hooks.install(self.repository, SOURCE / "xcode_editor.py")
        relocated = self.base / "moved project"
        self.root.rename(relocated)
        self.root = relocated
        self.repository = Repository(relocated)
        target = hooks.install(self.repository, SOURCE / "xcode_editor.py")
        self.assertEqual(self.repository.effective_hooks_path(), str(target))
        self.git("checkout", "--detach", "HEAD")
        self.assertTrue((relocated / "buildServer.json").is_file())
        hooks.uninstall(self.repository)
        self.assertIsNone(self.repository.local_hooks_path())

    def test_bare_repository_configuration_and_external_checkout(self):
        bare = self.base / "bare.git"
        self.git("clone", "--quiet", "--bare", str(self.root), str(bare))
        repository = Repository(bare)
        save_config(repository, self.config)
        hooks.install(repository, SOURCE / "xcode_editor.py")
        checkout = self.base / "bare checkout"
        self.git("worktree", "add", "--detach", str(checkout), "main", root=bare)
        self.assertTrue((checkout / "buildServer.json").is_file())
        self.assertEqual(Repository(checkout).common, bare)
