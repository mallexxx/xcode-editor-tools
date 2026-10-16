"""Generate local files with explicit ownership and no tracked-file edits."""
import hashlib
import json
from pathlib import Path

from runtime.editor_support import (
    PROFILE_PATH, atomic_write, git, has_symlink, json_bytes,
    normalize_config, render_bsp,
)
from .workspace import render_workspace

SOURCE = Path(__file__).resolve().parents[1]
EXCLUDE_BEGIN = "# BEGIN xcode-editor-tools"
EXCLUDE_END = "# END xcode-editor-tools"


def load_config(repository):
    if not repository.config_path.is_file():
        raise ValueError(f"No editor configuration: run init or supply --config ({repository.config_path})")
    return normalize_config(json.loads(repository.config_path.read_text()))


def save_config(repository, config):
    config = normalize_config(config)
    atomic_write(repository.config_path, json_bytes(config))
    return config


def add_excludes(repository, config):
    path = repository.common / "info/exclude"
    if path.is_symlink():
        raise ValueError(f"Refusing to replace symlinked local excludes: {path}")
    text = path.read_text() if path.exists() else ""
    patterns = ["/" + config["workspace_file"], "/" + config["scripts_dir"] + "/",
                "/.vscode/", "/buildServer.json", "/.build/xcode-editor/",
                "/" + str(Path(config["state_manifest"]).parent) + "/"]
    patterns = ["".join("\\" + c if c in "\\*?[]" else c for c in p) for p in patterns]
    # Preserve previous local rules. The managed block is for this installation.
    prefix, separator, tail = text.partition(EXCLUDE_BEGIN + "\n")
    if separator:
        _, end, suffix = tail.partition(EXCLUDE_END)
        if not end:
            raise ValueError("Incomplete managed block in local excludes; preserved for review")
    else:
        prefix, suffix = text.rstrip() + "\n\n", "\n"
    block = EXCLUDE_BEGIN + "\n" + "\n".join(dict.fromkeys(patterns)) + "\n" + EXCLUDE_END
    content = (prefix + block + suffix).encode()
    if not path.is_file() or path.read_bytes() != content:
        atomic_write(path, content)


def apply(repository, root, config=None, dry_run=False):
    root = Path(root).resolve()
    if not repository.contains(root):
        raise ValueError(f"Worktree belongs to another repository: {root}")
    config = normalize_config(config) if config else load_config(repository)
    container = root / config["container"]
    if not container.is_dir():
        return {"root": str(root), "skipped": f"container missing: {config['container']}", "written": [], "preserved": []}
    if has_symlink(root, config["state_manifest"]) or has_symlink(root, PROFILE_PATH):
        raise ValueError(f"Refusing symlinked editor state in {root}")
    stamp = root / config["state_manifest"]
    previous = json.loads(stamp.read_text()) if stamp.is_file() else {}
    if not isinstance(previous, dict) or any(not isinstance(v, str) for v in previous.values()):
        raise ValueError(f"Invalid ownership manifest: {stamp}")
    hashes = dict(previous)
    tracked = set(git(root, "ls-files", "-z").stdout.split("\0"))
    written = []
    preserved = []

    def put(relative, content, mode=0o644):
        path = root / relative
        if relative in tracked or has_symlink(root, relative):
            preserved.append(relative)
            return False
        digest = hashlib.sha256(content).hexdigest()
        if path.exists():
            if not path.is_file():
                preserved.append(relative)
                return False
            old = hashlib.sha256(path.read_bytes()).hexdigest()
            if old == digest:
                hashes[relative] = digest
                return True
            if previous.get(relative) != old:
                preserved.append(relative)
                return False
        written.append(relative)
        if not dry_run:
            atomic_write(path, content, mode)
        hashes[relative] = digest
        return True

    if not dry_run:
        # Fail before generating any files if the shared local rules are unsafe.
        add_excludes(repository, config)
    if not put(PROFILE_PATH, json_bytes(config)):
        raise ValueError(f"Runtime configuration was customized; update it or restore its managed version: {root / PROFILE_PATH}")
    for source in sorted((SOURCE / "runtime").iterdir()):
        if not source.is_file() or source.name == "__init__.py" or source.suffix == ".pyc":
            continue
        mode = 0o755 if source.suffix in (".py", ".sh") else 0o644
        put(config["scripts_dir"] + "/" + source.name, source.read_bytes(), mode)
    workspace = render_workspace(config, root)
    put(config["workspace_file"], json_bytes(workspace))
    for section in ("settings", "tasks", "launch", "extensions"):
        put(f".vscode/{section}.json", json_bytes(workspace[section]))
    put("buildServer.json", json_bytes(render_bsp(root, config)))
    if not dry_run:
        atomic_write(stamp, json_bytes(hashes))
    return {"root": str(root), "written": written, "preserved": preserved, "skipped": None}


def summary(result, dry_run=False):
    if result["skipped"]:
        return f"{result['root']}: skipped ({result['skipped']})"
    action = "would be written" if dry_run else "written"
    return f"{result['root']}: {len(result['written'])} files {action}, {len(result['preserved'])} existing/tracked files preserved"
