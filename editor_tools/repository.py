"""Discover Git repositories without assuming a checkout or bare layout."""
from pathlib import Path
from runtime.editor_support import git


class Repository:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.common = Path(git(self.path, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()).resolve()
        self.state = self.common / "xcode-editor"
        self.config_path = self.state / "config.json"

    def worktrees(self):
        result = git(self.path, "worktree", "list", "--porcelain", "-z").stdout
        roots = []
        for entry in result.split("\0\0"):
            fields = entry.split("\0")
            if fields[0].startswith("worktree ") and "bare" not in fields:
                roots.append(Path(fields[0][9:]).resolve())
        return roots

    def contains(self, root):
        return Repository(root).common == self.common

    def local_hooks_path(self):
        result = git(self.path, "config", "--local", "--get", "core.hooksPath", check=False)
        return result.stdout.strip() if result.returncode == 0 else None

    def effective_hooks_path(self):
        result = git(self.path, "config", "--get", "core.hooksPath", check=False)
        return result.stdout.strip() if result.returncode == 0 else None
