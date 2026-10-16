#!/usr/bin/env python3
"""Index worktrees with sourcekit-lsp while no editor is using them.

Runs sourcekit-lsp headless against buildServer.json (sourcekit-xcode-bsp),
waits until background indexing finishes and exits, so opening the worktree
in VS Code/Cursor later starts from an up-to-date index.

A worktree is skipped when it hasn't changed since its last index or when an
editor's build server is serving it. With --if-idle nothing runs while Xcode,
VS Code or Cursor is open. An editor that starts during indexing stops the
indexer (see sourcekit-xcode-bsp.sh), so the two never share a build root.
"""
import argparse
import hashlib
import json
import os
import pathlib
import queue
import signal
import subprocess
import sys
import threading
import time

from editor_support import load_worktree_config, git_environment

# Command line fragments of editors' main processes, for pgrep -f.
EDITORS = [
    "Xcode.app/Contents/MacOS/Xcode",
    "Visual Studio Code.app/Contents/MacOS/",
    "Visual Studio Code - Insiders.app/Contents/MacOS/",
    "Cursor.app/Contents/MacOS/",
    "VSCodium.app/Contents/MacOS/",
]
LOGGED_METHODS = {"window/logMessage", "window/showMessage", "$/progress"}
# Indexing is done when its progress ended and didn't restart for this long.
QUIET_SECONDS = 60
# Give up when indexing doesn't start, e.g. because the build server failed.
START_TIMEOUT_SECONDS = 300


def parse_args():
    summary = __doc__.split("\n\n")[0]
    parser = argparse.ArgumentParser(description=summary)
    parser.add_argument("worktrees", nargs="*",
                        help="worktree roots (default: current directory)")
    parser.add_argument("--all", action="store_true",
                        help="every worktree of the repository set up by "
                             "setup-build-server.py")
    parser.add_argument("--if-idle", action="store_true",
                        help="skip while Xcode, VS Code or Cursor is running")
    parser.add_argument("--force", action="store_true",
                        help="index even if nothing changed since last run")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="give up on a worktree after this many seconds "
                             "(default 3600)")
    parser.add_argument("--log", metavar="FILE",
                        help="append sourcekit-lsp and build server messages "
                             "to FILE")
    return parser.parse_args()


def log(*items):
    stamp = time.strftime("%H:%M:%S")
    print(f"[{stamp}]", *items, flush=True)


def git(root, *args):
    command = ["git", "-C", root, *args]
    return subprocess.run(command, capture_output=True, text=True, env=git_environment()).stdout


def is_configured(path):
    """Whether setup-build-server.py generated the worktree's buildServer.json."""
    config_path = os.path.join(path, "buildServer.json")
    try:
        config = load_worktree_config(path)
    except (OSError, ValueError):
        return False
    setup = os.path.join(path, config["scripts_dir"], "setup-build-server.py")
    if not os.path.exists(config_path) or not os.path.exists(setup):
        return False
    try:
        config = json.loads(pathlib.Path(config_path).read_text())
    except (OSError, ValueError):
        return False
    return config.get("name") == "sourcekit-xcode-bsp"


def configured_worktrees(root):
    """Worktrees of the repository at root set up for VS Code."""
    listing = git(root, "worktree", "list", "--porcelain", "-z")
    paths = [record.split("\0")[0][9:] for record in listing.split("\0\0")
             if record.startswith("worktree ") and "bare" not in record.split("\0")]
    return [path for path in paths if is_configured(path)]


def live_pid(pid_file):
    """The pid in the file if it's a running sourcekit process, else None;
    a stale file may name a reused pid of an unrelated process."""
    try:
        pid = int(pathlib.Path(pid_file).read_text().strip())
    except (OSError, ValueError):
        return None
    command = ["ps", "-p", str(pid), "-o", "command="]
    result = subprocess.run(command, capture_output=True, text=True)
    return pid if "sourcekit" in result.stdout else None


def running_editor():
    for fragment in EDITORS:
        result = subprocess.run(["pgrep", "-f", fragment], capture_output=True)
        if result.returncode == 0:
            return fragment.split(".app")[0]
    return None


def worktree_state(root):
    """Hash of HEAD, uncommitted changes and the modification times of the
    changed files; equal hashes mean no reindex."""
    status = git(root, "status", "--porcelain", "-z")
    times = []
    records = iter(status.split("\0"))
    for record in records:
        if not record:
            continue
        name = record[3:]
        if record[:1] in ("R", "C"):
            next(records, None)
        path = os.path.join(root, name)
        if os.path.isfile(path):
            info = os.stat(path)
            times.append(f"{name}:{info.st_mtime_ns}:{info.st_size}")
    state = git(root, "rev-parse", "HEAD") + status + "\n".join(times)
    for relative in ("buildServer.json", ".build/xcode-editor/config.json"):
        path = pathlib.Path(root) / relative
        if path.is_file():
            state += path.read_text()
    return hashlib.sha256(state.encode()).hexdigest()


def children(pid):
    result = subprocess.run(["pgrep", "-P", str(pid)],
                            capture_output=True, text=True)
    return [int(child) for child in result.stdout.split()]


class LSPClient:
    """Minimal JSON-RPC client over the sourcekit-lsp stdio pipes."""

    def __init__(self, root):
        environment = dict(os.environ, XCODE_EDITOR_BACKGROUND_INDEXER="1")
        self.proc = subprocess.Popen(
            ["xcrun", "sourcekit-lsp"], cwd=root, env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
        self.messages = queue.Queue()
        self.next_id = 0
        threading.Thread(target=self.read_loop, daemon=True).start()

    def read_message(self):
        """Reads one message; None when the stream ends."""
        length = 0
        while True:
            line = self.proc.stdout.readline()
            if not line:
                return None
            line = line.decode().strip()
            if not line:
                return json.loads(self.proc.stdout.read(length))
            key, value = line.split(":", 1)
            if key.lower() == "content-length":
                length = int(value)

    def read_loop(self):
        while True:
            message = self.read_message()
            self.messages.put(message)
            if message is None:
                return

    def write(self, message):
        body = json.dumps(message).encode()
        header = b"Content-Length: %d\r\n\r\n" % len(body)
        self.proc.stdin.write(header + body)
        self.proc.stdin.flush()

    def request(self, method, params):
        self.next_id += 1
        self.write({"jsonrpc": "2.0", "id": self.next_id,
                    "method": method, "params": params})

    def notify(self, method, params):
        self.write({"jsonrpc": "2.0", "method": method, "params": params})

    def reply_null(self, message):
        self.write({"jsonrpc": "2.0", "id": message["id"], "result": None})

    def stop(self, server_pid_file):
        """Stops sourcekit-lsp, the build server it started and the server's
        swift-build service; each runs in its own process group."""
        pids = [self.proc.pid]
        server = live_pid(server_pid_file)
        if server:
            pids = children(server) + [server] + pids
        if os.path.exists(server_pid_file):
            os.remove(server_pid_file)
        for pid in pids:
            for kill in (os.killpg, os.kill):
                try:
                    kill(pid, signal.SIGTERM)
                except OSError:
                    pass


def indexing_event(message):
    """("begin" | "end", token) for sourcekit-lsp's Indexing progress."""
    if message.get("method") != "$/progress":
        return None
    params = message["params"]
    value = params.get("value", {})
    kind = value.get("kind")
    if kind == "begin" and value.get("title") == "Indexing":
        return "begin", params["token"]
    if kind == "end":
        return "end", params["token"]
    return None


def write_log(log_file, message):
    if not log_file or message.get("method") not in LOGGED_METHODS:
        return
    params = message["params"]
    text = params.get("message") or json.dumps(params.get("value", params))
    log_file.write(time.strftime("%H:%M:%S ") + text + "\n")


def initialize(client, root):
    options = {
        "backgroundIndexing": True,
        "index": {"maxCoresPercentageToUseForBackgroundIndexing": 1.0},
    }
    client.request("initialize", {
        "processId": os.getpid(),
        "rootUri": pathlib.Path(root).as_uri(),
        "capabilities": {"window": {"workDoneProgress": True}},
        "initializationOptions": options,
    })
    client.notify("initialized", {})


def wait_for_index(client, timeout, log_file):
    """Waits until Indexing progress ends and stays quiet."""
    active = set()
    started = False
    finished_at = None
    begin = time.time()
    while time.time() < begin + timeout:
        quiet = finished_at and time.time() - finished_at > QUIET_SECONDS
        if quiet and not active:
            return "done"
        if not started and time.time() > begin + START_TIMEOUT_SECONDS:
            return "indexing didn't start"
        try:
            message = client.messages.get(timeout=5)
        except queue.Empty:
            continue
        if message is None:
            return "stopped"
        if "id" in message and "method" in message:
            client.reply_null(message)
        write_log(log_file, message)
        event = indexing_event(message)
        if event and event[0] == "begin":
            active.add(event[1])
            started = True
        if event and event[0] == "end" and event[1] in active:
            active.discard(event[1])
            finished_at = time.time()
    return "timeout"


def index_worktree(root, args, log_file):
    state_dir = os.path.join(root, ".build", "bsp")
    state_file = os.path.join(state_dir, "indexed-state")
    if live_pid(os.path.join(state_dir, "server.pid")):
        return log(root, ": an editor is using it, skipping")
    state = worktree_state(root)
    previous = pathlib.Path(state_file).read_text() if os.path.exists(state_file) else ""
    if state == previous and not args.force:
        return log(root, ": unchanged since the last index, skipping")
    config = load_worktree_config(root)
    setup = os.path.join(root, config["scripts_dir"], "setup-build-server.py")
    result = subprocess.run([setup], capture_output=True, text=True)
    if result.returncode != 0:
        return log(root, ": setup failed:", result.stdout.strip())
    os.makedirs(state_dir, exist_ok=True)
    started = time.time()
    log(root, ": indexing")
    client = LSPClient(root)
    pid_file = os.path.join(state_dir, "indexer.pid")
    try:
        pathlib.Path(pid_file).write_text(str(client.proc.pid))
        initialize(client, root)
        result = wait_for_index(client, args.timeout, log_file)
    finally:
        client.stop(os.path.join(state_dir, "indexer-server.pid"))
        if os.path.exists(pid_file):
            os.remove(pid_file)
    log(root, f": {result} in {int(time.time() - started)}s")
    if result == "done":
        pathlib.Path(state_file).write_text(state)


def main():
    args = parse_args()
    worktrees = args.worktrees or [os.getcwd()]
    if args.all:
        worktrees = configured_worktrees(worktrees[0])
    log_file = open(args.log, "a", buffering=1) if args.log else None
    for worktree in worktrees:
        editor = args.if_idle and running_editor()
        if editor:
            return log(f"{editor} is running, skipping")
        try:
            index_worktree(os.path.abspath(worktree), args, log_file)
        except OSError as error:
            log(worktree, ": failed:", error)
    return 0


if __name__ == "__main__":
    sys.exit(main())
