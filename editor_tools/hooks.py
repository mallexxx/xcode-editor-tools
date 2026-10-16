"""Chain existing Git hooks and restore their configuration on uninstall."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

from runtime.editor_support import atomic_write, git, json_bytes
from .repository import Repository

MARKER = "# Managed by xcode-editor-tools"


def installation_path(repository):
    return repository.state / "installation.json"


def original_directory(repository, previous, cwd):
    if previous is None:
        return repository.common / "hooks"
    path = Path(previous)
    return path if path.is_absolute() else Path(cwd) / path


def install(repository, entry_point, adopt_sha256=None):
    path = installation_path(repository)
    state = json.loads(path.read_text()) if path.is_file() else None
    managed = repository.state / "hooks"
    current = repository.effective_hooks_path()
    if state and state.get("active"):
        if current not in (str(managed), state.get("managed_directory", str(managed))):
            raise ValueError("core.hooksPath changed after installation; refusing to overwrite it")
    else:
        state = {
            "previous_effective_hooks_path": current,
            "previous_local_hooks_path": repository.local_hooks_path(),
        }
    previous = state["previous_effective_hooks_path"]
    directories = {original_directory(repository, previous, root) for root in repository.worktrees()}
    directories.add(original_directory(repository, previous, repository.path))
    if adopt_sha256:
        originals = [p / "post-checkout" for p in directories if (p / "post-checkout").is_file()]
        if not originals or any(hashlib.sha256(p.read_bytes()).hexdigest() != adopt_sha256 for p in originals):
            raise ValueError("Existing post-checkout does not match the supplied adoption hash")
        state["adopted_post_checkout_sha256"] = adopt_sha256
    # Only wrap hooks that actually exist, plus our post-checkout hook. A
    # no-op push-to-checkout/proc-receive hook would change Git's defaults.
    names = {"post-checkout"}
    for directory in directories:
        if directory.is_dir():
            names.update(p.name for p in directory.iterdir()
                         if p.is_file() and os.access(p, os.X_OK) and not p.name.endswith(".sample"))
    names.update(state.get("hook_names", []))
    for name in sorted(names):
        if "/" in name or name in (".", ".."):
            raise ValueError("Invalid hook name")
        target = managed / name
        command = ["/usr/bin/env", "python3", str(Path(entry_point).resolve()), "_hook", str(repository.common), name, "--"]
        content = "#!/bin/sh\n" + MARKER + "\nexec " + " ".join(shlex.quote(v) for v in command) + ' "$@"\n'
        if target.exists() and MARKER not in target.read_text():
            raise ValueError(f"Existing hook preserved: {target}")
        atomic_write(target, content.encode(), 0o755)
    state.update({"active": True, "entry_point": str(Path(entry_point).resolve()),
                  "managed_directory": str(managed), "hook_names": sorted(names)})
    atomic_write(path, json_bytes(state))
    git(repository.path, "config", "--local", "core.hooksPath", str(managed))
    return managed


def uninstall(repository):
    path = installation_path(repository)
    if not path.is_file():
        raise ValueError("No hook installation found")
    state = json.loads(path.read_text())
    if not state.get("active"):
        return
    managed = repository.state / "hooks"
    if repository.effective_hooks_path() not in (str(managed), state.get("managed_directory", str(managed))):
        raise ValueError("core.hooksPath changed after installation; refusing to overwrite it")
    previous = state["previous_local_hooks_path"]
    if previous is None:
        git(repository.path, "config", "--local", "--unset", "core.hooksPath")
    else:
        git(repository.path, "config", "--local", "core.hooksPath", previous)
    state["active"] = False
    atomic_write(path, json_bytes(state))


def run(common, name, arguments):
    repository = Repository(common)
    state = json.loads(installation_path(repository).read_text())
    original = original_directory(repository, state["previous_effective_hooks_path"], Path.cwd()) / name
    adopted = (name == "post-checkout" and original.is_file()
               and hashlib.sha256(original.read_bytes()).hexdigest() == state.get("adopted_post_checkout_sha256"))
    status = 0
    if original.is_file() and os.access(original, os.X_OK) and not adopted:
        # Inherit cwd, environment, stdin and output exactly as Git supplied them.
        try:
            status = subprocess.run([str(original), *arguments]).returncode
        except OSError as error:
            if error.errno != 8:  # Git also accepts executable scripts without a shebang.
                raise
            status = subprocess.run(["/bin/sh", str(original), *arguments]).returncode
    if name == "post-checkout" and len(arguments) >= 3 and arguments[2] == "1":
        try:
            from .bootstrap import apply, summary
            root = git(Path.cwd(), "rev-parse", "--show-toplevel").stdout.strip()
            print(summary(apply(repository, root)))
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            print(f"xcode-editor: setup failed; checkout completed: {error}", file=sys.stderr)
    return status if status >= 0 else 128 - status
