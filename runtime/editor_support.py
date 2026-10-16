#!/usr/bin/env python3
"""Configuration and path helpers shared by the CLI and generated scripts."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile

PROFILE_PATH = ".build/xcode-editor/config.json"
DEFAULT_SERVER = {
    "repository": "https://github.com/mallexxx/sourcekit-xcode-bsp.git",
    "revision": "afd0e3dd026b3ee3619e2271809debee25fec96f",
    "install_dir": "~/.local/opt/sourcekit-xcode-bsp",
}


def git_environment():
    # Hooks export Git directory/index variables. Do not accidentally inspect
    # another worktree with the caller's index or repository override.
    local = {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX",
             "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_SHALLOW_FILE",
             "GIT_GRAFT_FILE", "GIT_IMPLICIT_WORK_TREE", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"}
    return {key: value for key, value in os.environ.items()
            if key not in local and not key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))}


def git(root, *arguments, check=True):
    return subprocess.run(
        ["git", "-C", str(root), *arguments], env=git_environment(),
        check=check, capture_output=True, text=True,
    )


def relative_path(value, field):
    if not isinstance(value, str) or not value or any(c in value for c in "\0\r\n"):
        raise ValueError(f"{field} must be a nonempty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path == PurePosixPath("."):
        raise ValueError(f"{field} must stay inside the worktree: {value}")
    if ".git" in path.parts:
        raise ValueError(f"{field} cannot write inside .git")
    return str(path)


def normalize_config(value):
    config = copy.deepcopy(value)
    if config.get("schema_version", 1) != 1:
        raise ValueError("Unsupported configuration schema_version")
    config["schema_version"] = 1
    config["container"] = relative_path(config.get("container"), "container")
    suffix = Path(config["container"]).suffix
    if suffix not in (".xcworkspace", ".xcodeproj"):
        raise ValueError("container must name an .xcworkspace or .xcodeproj")
    name = Path(config["container"]).stem
    config["workspace_file"] = relative_path(config.get("workspace_file", f"{name}.code-workspace"), "workspace_file")
    if not config["workspace_file"].endswith(".code-workspace"):
        raise ValueError("workspace_file must end in .code-workspace")
    config["scripts_dir"] = relative_path(config.get("scripts_dir", "scripts/vscode"), "scripts_dir")
    config["state_manifest"] = relative_path(config.get("state_manifest", ".build/xcode-editor/files.json"), "state_manifest")
    if Path(config["workspace_file"]).parent != Path("."):
        raise ValueError("workspace_file must live at the worktree root")
    config.setdefault("configuration", "Debug")
    if not isinstance(config["configuration"], str) or not config["configuration"]:
        raise ValueError("configuration must be a nonempty string")
    config["build_server"] = {**DEFAULT_SERVER, **config.get("build_server", {})}
    server = config["build_server"]
    if not re.fullmatch(r"[0-9a-fA-F]{40}", server["revision"]):
        raise ValueError("build_server.revision must be a full Git commit SHA")
    config.setdefault("build_arguments", ["-skipPackagePluginValidation", "-skipMacroValidation"])
    if not isinstance(config["build_arguments"], list) or any(not isinstance(v, str) for v in config["build_arguments"]):
        raise ValueError("build_arguments must be an array of strings")
    profiles = config.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError("profiles must contain at least one platform")
    for key, profile in profiles.items():
        if key not in ("macos", "ios") or not isinstance(profile, dict):
            raise ValueError("Supported profile names are macos and ios")
        profile.setdefault("sdk", "macosx" if key == "macos" else "iphonesimulator")
        profile.setdefault("label", "macOS" if key == "macos" else "iOS")
        profile.setdefault("scheme", name)
        profile.setdefault("schemes", [profile["scheme"]])
        profile.setdefault("targets", {"include": [], "exclude": []})
        for pattern in profile["targets"].get("include", []) + profile["targets"].get("exclude", []):
            re.compile(pattern)
        for directory in profile.get("exclude_package_directories", []):
            relative_path(directory, "exclude_package_directories")
        if profile.get("app_path"):
            relative_path(profile["app_path"], "app_path")
        if profile.get("executable"):
            relative_path(profile["executable"], "executable")
    config.setdefault("default_platform", next(iter(profiles)))
    if config["default_platform"] not in profiles:
        raise ValueError("default_platform must name a configured profile")
    config.setdefault("compatibility", {})
    return config


def find_root(start=None):
    start = Path(start or __file__).resolve()
    if start.is_file():
        start = start.parent
    return Path(git(start, "rev-parse", "--show-toplevel").stdout.strip()).resolve()


def load_worktree_config(root):
    return normalize_config(json.loads((Path(root) / PROFILE_PATH).read_text()))


def atomic_write(path, data, mode=0o644):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def json_bytes(value):
    return (json.dumps(value, indent=2) + "\n").encode()


def has_symlink(root, relative):
    path = Path(root)
    for part in Path(relative).parts:
        path /= part
        if path.is_symlink():
            return True
    return False


def xcode_hash(path):
    digest = hashlib.md5(str(path).encode()).digest()

    def letters(number):
        result = ""
        for _ in range(14):
            result = chr(ord("a") + number % 26) + result
            number //= 26
        return result

    return letters(int.from_bytes(digest[:8], "big")) + letters(int.from_bytes(digest[8:], "big"))


def derived_data_root():
    try:
        result = subprocess.run(
            ["defaults", "read", "com.apple.dt.Xcode", "IDECustomDerivedDataLocation"],
            capture_output=True, text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip()).expanduser()
    except FileNotFoundError:
        pass
    return Path.home() / "Library/Developer/Xcode/DerivedData"


def derived_data(root, config):
    container = Path(root).resolve() / config["container"]
    # Foundation standardizes existing /private/{tmp,var,etc} paths to the
    # corresponding public alias; Xcode hashes that spelling, unlike realpath.
    if sys.platform == "darwin" and str(container).startswith("/private/"):
        alias = Path(str(container)[len("/private"):])
        if alias.exists() and container.exists() and alias.samefile(container):
            container = alias
    return derived_data_root() / f"{container.stem}-{xcode_hash(container)}"


def current_platform(root, config):
    try:
        sdk = json.loads((Path(root) / "buildServer.json").read_text()).get("platform")
    except (OSError, ValueError):
        return config["default_platform"]
    return next((name for name, profile in config["profiles"].items() if profile["sdk"] == sdk), config["default_platform"])


def target_filter(root, profile):
    result = copy.deepcopy(profile.get("targets", {}))
    excluded = list(profile.get("exclude_projects", []))
    for relative in profile.get("exclude_package_directories", []):
        directory = Path(root) / relative
        if directory.is_dir():
            excluded += sorted(p.name for p in directory.iterdir() if not p.name.startswith(".") and (p / "Package.swift").is_file())
    if excluded:
        result["exclude"] = [f"^({'|'.join(re.escape(n) for n in excluded)})/"] + result.get("exclude", [])
    return result


def render_bsp(root, config, platform=None):
    root = Path(root).resolve()
    platform = platform or current_platform(root, config)
    if platform not in config["profiles"]:
        raise ValueError(f"Platform {platform!r} is not configured")
    profile = config["profiles"][platform]
    result = {
        "name": "sourcekit-xcode-bsp", "version": "0.1.0", "bspVersion": "2.1.0",
        "languages": ["swift", "objective-c", "objective-cpp", "c", "cpp"],
        "argv": [str(root / config["scripts_dir"] / "sourcekit-xcode-bsp.sh")],
        "workspace": str(root / config["container"]),
        "buildRoot": str(derived_data(root, config)), "derivedDataLayout": "xcode",
        "platform": profile["sdk"], "configuration": config["configuration"],
        "targets": target_filter(root, profile),
    }
    if config.get("build_settings"):
        result["buildSettings"] = config["build_settings"]
    return result


def server_path(config):
    installed = Path(config["build_server"]["install_dir"]).expanduser() / "sourcekit-xcode-bsp"
    return os.environ.get("SOURCEKIT_XCODE_BSP", str(installed) if os.access(installed, os.X_OK) else "sourcekit-xcode-bsp")


def setup_server(root, platform=None):
    config = load_worktree_config(root)
    server = server_path(config)
    if not shutil.which(server):
        raise ValueError("Build server not found; run install-build-server.sh or set SOURCEKIT_XCODE_BSP")
    supported = subprocess.run([server, "list-targets", "--help"], capture_output=True)
    if supported.returncode:
        raise ValueError("This build server lacks target-selection support; install the pinned fork")
    stamp = Path(config["build_server"]["install_dir"]).expanduser() / "revision"
    if stamp.is_file() and stamp.read_text().strip() != config["build_server"]["revision"]:
        print("warning: installed build-server revision differs from the configured pin")
    result = render_bsp(root, config, platform)
    content = json_bytes(result)
    target = Path(root) / "buildServer.json"
    if has_symlink(root, "buildServer.json"):
        raise ValueError("Refusing to replace a symlinked buildServer.json")
    if target.is_file() and target.read_bytes() == content:
        print(f"buildServer.json is up to date ({result['platform']})")
    else:
        atomic_write(target, content)
        print(f"Wrote {target} ({result['platform']}); restart the language server if already running")
    return 0


def environment_enabled(config, name, compatibility_key):
    legacy = config["compatibility"].get(compatibility_key)
    return bool(os.environ.get(name) or (legacy and os.environ.get(legacy)))


def background_label(root, config):
    if config.get("background_label"):
        return config["background_label"]
    common = git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    return "local.xcode-editor.background-indexing." + hashlib.sha256(common.encode()).hexdigest()[:12]


def helper_main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["get", "build-arguments", "write-debug-settings"])
    parser.add_argument("values", nargs="*")
    args = parser.parse_args()
    root = find_root()
    config = load_worktree_config(root)
    if args.command == "build-arguments":
        for value in config["build_arguments"]:
            sys.stdout.buffer.write(value.encode() + b"\0")
        return 0
    cache = environment_enabled(config, "XCODE_EDITOR_WORKTREE_CACHE", "worktree_cache_environment")
    if args.command == "write-debug-settings":
        if len(args.values) != 1:
            parser.error("write-debug-settings requires the DerivedData path")
        if cache:
            # JSON quoting also quotes LLDB command arguments, including spaces
            # and apostrophes in filesystem paths.
            pairs = ["/^wt", str(root), "/^dd", args.values[0]]
            content = "settings set target.source-map " + " ".join(json.dumps(p) for p in pairs) + "\n"
        else:
            content = "# Regular build: debug info has real paths, no source map.\n"
        atomic_write(root / ".build/debug.lldbinit", content.encode())
        return 0
    if len(args.values) != 1:
        parser.error("get requires one property")
    ios = config["profiles"].get("ios", {})
    values = {
        "root": str(root), "container": str(root / config["container"]),
        "container_flag": "-workspace" if config["container"].endswith(".xcworkspace") else "-project",
        "configuration": config["configuration"], "cache_enabled": "1" if cache else "",
        "background_indexer": "1" if environment_enabled(config, "XCODE_EDITOR_BACKGROUND_INDEXER", "background_indexer_environment") else "",
        "server": server_path(config), "derived_data": str(derived_data(root, config)),
        "simulator_scheme": ios.get("scheme", ""),
        "simulator_app": str(root / ".build/products" / ios["app_path"]) if ios.get("app_path") else "",
        "simulator_device_prefix": ios.get("device_prefix", "iPhone"),
        "background_label": background_label(root, config),
    }
    if args.values[0] not in values:
        parser.error("Unknown property: " + args.values[0])
    print(values[args.values[0]])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(helper_main())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
