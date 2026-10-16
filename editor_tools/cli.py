"""Command-line entry point. All repository configuration stays in Git's local data."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from runtime.editor_support import normalize_config
from . import __version__
from .bootstrap import apply, load_config, save_config, summary
from .repository import Repository
from . import hooks


def initial_config(root, container=None, scheme=None, platform="macos", app=None, test_scheme=None):
    root = Path(root).resolve()
    if container is None:
        # A project contains its own internal .xcworkspace; only examine the
        # checkout root, so that internal workspace is not mistaken for a choice.
        workspaces = sorted(root.glob("*.xcworkspace"))
        candidates = workspaces or sorted(root.glob("*.xcodeproj"))
        if len(candidates) != 1:
            raise ValueError("Specify --workspace or --project when the checkout has no unique top-level container")
        container = candidates[0].name
    container = normalize_config({"container": container, "profiles": {platform: {}}})["container"]
    if not (root / container).is_dir():
        raise ValueError(f"Xcode container does not exist: {root / container}")
    name = Path(container).stem
    profile = {"scheme": scheme or name}
    if app:
        product = app if app.endswith(".app") else app + ".app"
        folder = "Debug" if platform == "macos" else "Debug-iphonesimulator"
        profile["app_path"] = folder + "/" + product
    if test_scheme:
        profile["test_scheme"] = test_scheme
    return normalize_config({"container": container, "default_platform": platform, "profiles": {platform: profile}})


def parser():
    result = argparse.ArgumentParser(description="Local VS Code/Cursor support for Xcode projects and Git worktrees")
    result.add_argument("--version", action="version", version=__version__)
    sub = result.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="create private per-repository configuration")
    init.add_argument("--repo", default=".")
    containers = init.add_mutually_exclusive_group()
    containers.add_argument("--workspace")
    containers.add_argument("--project")
    init.add_argument("--scheme")
    init.add_argument("--test-scheme")
    init.add_argument("--app", help="app product name, if launch configurations are wanted")
    init.add_argument("--platform", choices=["macos", "ios"], default="macos")
    init.add_argument("--config", type=Path, help="use a complete JSON configuration instead of discovery")
    install = sub.add_parser("install", help="install the shared hook, preserving existing hooks")
    install.add_argument("--repo", default=".")
    install.add_argument("--adopt-hook-sha256", help="skip an older post-checkout hook only if its content matches this hash")
    uninstall = sub.add_parser("uninstall", help="restore the previous core.hooksPath; leave local generated files intact")
    uninstall.add_argument("--repo", default=".")
    populate = sub.add_parser("apply", help="generate or update local worktree files")
    populate.add_argument("path", nargs="?", type=Path)
    populate.add_argument("--repo", default=".")
    populate.add_argument("--all", action="store_true")
    populate.add_argument("--dry-run", action="store_true")
    status = sub.add_parser("status", help="show installation, configuration and registered worktrees")
    status.add_argument("--repo", default=".")
    server = sub.add_parser("install-server", help="build the pinned BSP server; never run implicitly")
    server.add_argument("--repo", default=".")
    return result


def main(arguments=None):
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    try:
        if arguments and arguments[0] == "_hook":
            if len(arguments) < 4 or arguments[3] != "--":
                raise ValueError("Invalid internal hook invocation")
            return hooks.run(arguments[1], arguments[2], arguments[4:])
        args = parser().parse_args(arguments)
        repository = Repository(args.repo)
        if args.command == "init":
            if repository.config_path.exists():
                raise ValueError(f"Configuration already exists; edit it directly: {repository.config_path}")
            if args.config:
                config = json.loads(args.config.read_text())
            else:
                roots = repository.worktrees()
                checkout = repository.path if repository.path in roots else next(iter(roots), None)
                if checkout is None:
                    raise ValueError("Create a checked-out worktree before initializing a bare repository")
                config = initial_config(checkout, args.workspace or args.project, args.scheme, args.platform, args.app, args.test_scheme)
            save_config(repository, config)
            print(f"Wrote private configuration: {repository.config_path}")
        elif args.command == "install":
            load_config(repository)
            entry = Path(__file__).resolve().parents[1] / "xcode_editor.py"
            target = hooks.install(repository, entry, args.adopt_hook_sha256)
            print(f"Installed shared hooks in {target}")
        elif args.command == "uninstall":
            hooks.uninstall(repository)
            print("Restored previous hook configuration; local generated files were retained")
        elif args.command == "apply":
            if args.all and args.path:
                raise ValueError("Use a worktree path or --all, not both")
            config = load_config(repository)
            roots = repository.worktrees() if args.all else [args.path or Path.cwd()]
            failures = []
            for root in roots:
                try:
                    print(summary(apply(repository, root, config, args.dry_run), args.dry_run))
                except (ValueError, OSError, subprocess.CalledProcessError) as error:
                    failures.append(str(root))
                    print(f"{root}: {error}", file=sys.stderr)
            return 1 if failures else 0
        elif args.command == "status":
            print(json.dumps({"common_directory": str(repository.common), "config": str(repository.config_path),
                              "hooks_path": repository.effective_hooks_path(),
                              "worktrees": [str(p) for p in repository.worktrees()]}, indent=2))
        elif args.command == "install-server":
            from runtime.install_server import install
            install(load_config(repository))
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
