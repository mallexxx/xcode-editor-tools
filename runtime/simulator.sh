#!/bin/bash
# Build an iOS scheme for a concrete simulator; launch suspended for lldb-dap.
set -euo pipefail
usage() {
    echo "Usage: $0 [--build-only|--no-build|--test SCHEME] [--only-testing TARGET] [simulator name or UDID]"
    echo "Uses the ios profile's scheme, app product and device prefix."
}
build=1
launch=1
test_scheme=""
only_testing=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --build-only) launch=""; shift ;;
        --no-build) build=""; shift ;;
        --test) test_scheme="${2:?--test requires a scheme}"; launch=""; shift 2 ;;
        --only-testing) only_testing="${2:?--only-testing requires a target}"; shift 2 ;;
        *) break ;;
    esac
done
script_dir="$(cd "$(dirname "$0")" && pwd)"
helper="${script_dir}/editor_support.py"
root="$(python3 "${helper}" get root)"
scheme="$(python3 "${helper}" get simulator_scheme)"
app="$(python3 "${helper}" get simulator_app)"
prefix="$(python3 "${helper}" get simulator_device_prefix)"
if [[ -z "${scheme}" || ( -z "${app}" && -z "${test_scheme}" ) ]]; then
    echo "Configure an ios profile with scheme and app_path first" >&2
    exit 1
fi
device="$(xcrun simctl list devices available --json | python3 -c '
import json,sys
name,prefix=sys.argv[1:]
devices=[d for group in json.load(sys.stdin)["devices"].values() for d in group]
match=[d for d in devices if name in (d["name"],d["udid"])]
booted=[d for d in devices if d["state"]=="Booted" and d["name"].startswith(prefix)]
available=[d for d in devices if d["name"].startswith(prefix)]
chosen=match if name else booted or available
print(chosen[0]["udid"] if chosen else "")
' "${1:-}" "${prefix}")"
if [[ -z "${device}" ]]; then echo "No matching simulator found" >&2; exit 1; fi
if [[ -n "${test_scheme}" ]]; then
    if [[ -n "${only_testing}" ]]; then
        exec "${script_dir}/xcodebuild.sh" test "${test_scheme}" "platform=iOS Simulator,id=${device}" "-only-testing:${only_testing}"
    fi
    exec "${script_dir}/xcodebuild.sh" test "${test_scheme}" "platform=iOS Simulator,id=${device}"
fi
if [[ -n "${build}" ]]; then
    "${script_dir}/xcodebuild.sh" build "${scheme}" "platform=iOS Simulator,id=${device}"
fi
[[ -n "${launch}" ]] || exit 0
if [[ ! -d "${app}" ]]; then echo "App product not found: ${app}" >&2; exit 1; fi
xcrun simctl boot "${device}" 2>/dev/null || true
open -a Simulator --args -CurrentDeviceUDID "${device}"
bundle_id="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "${app}/Info.plist")"
xcrun simctl terminate "${device}" "${bundle_id}" 2>/dev/null || true
xcrun simctl install "${device}" "${app}"
launch_output="$(xcrun simctl launch --wait-for-debugger "${device}" "${bundle_id}")"
pid="${launch_output##*: }"
mkdir -p "${root}/.build"
printf 'process attach --pid %s\n' "${pid}" > "${root}/.build/simulator-attach.lldb"
echo "Launched ${bundle_id} on ${device}, pid ${pid}, waiting for the debugger."
