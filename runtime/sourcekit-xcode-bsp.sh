#!/bin/bash
# Keep editor and headless preparation from using the same worktree together.
set -euo pipefail
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "Build-server launcher for sourcekit-lsp, configured through buildServer.json."
    exit 0
fi
script_dir="$(cd "$(dirname "$0")" && pwd)"
helper="${script_dir}/editor_support.py"
root="$(python3 "${helper}" get root)"
state_dir="${root}/.build/bsp"
mkdir -p "${state_dir}"
live_pid() {
    local pid
    pid="$(cat "$1" 2>/dev/null || true)"
    [[ "${pid}" =~ ^[0-9]+$ ]] || return 0
    [[ "$(ps -p "${pid}" -o command= 2>/dev/null)" == *sourcekit* ]] || return 0
    echo "${pid}"
}
stop_background_indexer() {
    local pids=() pid_file pid
    for pid_file in "${state_dir}/indexer-server.pid" "${state_dir}/indexer.pid"; do
        pid="$(live_pid "${pid_file}")"
        [[ -z "${pid}" ]] && continue
        pids+=("${pid}" $(pgrep -P "${pid}" || true))
        pkill -TERM -P "${pid}" 2>/dev/null || true
        kill -TERM -- "-${pid}" "${pid}" 2>/dev/null || true
    done
    for _ in $(seq 20); do
        [[ ${#pids[@]} -eq 0 ]] && break
        kill -0 "${pids[@]}" 2>/dev/null || break
        sleep 0.5
    done
}
if [[ -n "$(python3 "${helper}" get background_indexer)" ]]; then
    if [[ -n "$(live_pid "${state_dir}/server.pid")" ]]; then
        echo "An editor's build server is running for ${root}" >&2
        exit 1
    fi
    echo $$ > "${state_dir}/indexer-server.pid"
else
    stop_background_indexer
    echo $$ > "${state_dir}/server.pid"
fi
server="$(python3 "${helper}" get server)"
cd "${root}"
exec "${server}" serve
