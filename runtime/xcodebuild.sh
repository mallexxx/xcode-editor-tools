#!/bin/bash
# Build/test with regular Xcode parameters, or opt into shared compilation CAS.
set -euo pipefail

usage() {
    echo "Usage: $0 <build|test|build-for-testing|test-without-building> <scheme> [destination] [xcodebuild args...]"
    echo "Destination defaults to macOS. Configuration and container come from the repository profile."
    echo "XCODE_EDITOR_WORKTREE_CACHE=1 uses shared CAS and .build/xcodebuild."
}
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then usage; exit 0; fi
if [[ $# -lt 2 ]]; then usage >&2; exit 1; fi
action="$1"
scheme="$2"
destination="${3:-macOS}"
shift $(( $# < 3 ? $# : 3 ))
[[ "${destination}" == "macOS" ]] && destination="platform=macOS,arch=$(uname -m)"

script_dir="$(cd "$(dirname "$0")" && pwd)"
helper="${script_dir}/editor_support.py"
root="$(python3 "${helper}" get root)"
container="$(python3 "${helper}" get container)"
container_flag="$(python3 "${helper}" get container_flag)"
configuration="$(python3 "${helper}" get configuration)"
cache="$(python3 "${helper}" get cache_enabled)"
args=("${container_flag}" "${container}" -scheme "${scheme}" -configuration "${configuration}" -destination "${destination}")
while IFS= read -r -d '' argument; do args+=("${argument}"); done < <(python3 "${helper}" build-arguments)

if [[ -n "${cache}" ]]; then
    derived_data="${root}/.build/xcodebuild"
    cas="${HOME}/Library/Developer/Xcode/DerivedData/CompilationCache.noindex"
    prefix_maps="\"${derived_data}=/^dd\" \"${root}=/^wt\""
    args+=(
        COMPILATION_CACHE_ENABLE_CACHING=YES
        COMPILATION_CACHE_CAS_PATH="${cas}"
        SWIFT_ENABLE_PREFIX_MAPPING=YES
        CLANG_ENABLE_PREFIX_MAPPING=YES
        SWIFT_OTHER_PREFIX_MAPPINGS="${prefix_maps}"
        CLANG_OTHER_PREFIX_MAPPINGS="${prefix_maps}"
        -derivedDataPath "${derived_data}"
    )
else
    # Even pointing -derivedDataPath at Xcode's default changes build parameters.
    derived_data="$(python3 "${helper}" get derived_data)"
fi

mkdir -p "${root}/.build"
if [[ -e "${root}/.build/products" && ! -L "${root}/.build/products" ]]; then
    echo "Refusing to replace the existing .build/products directory" >&2
    exit 1
fi
ln -sfn "${derived_data}/Build/Products" "${root}/.build/products"
python3 "${helper}" write-debug-settings "${derived_data}"

formatter=(cat)
if command -v xcbeautify > /dev/null; then
    formatter=(xcbeautify --disable-colored-output --renderer terminal)
else
    echo "warning: xcbeautify unavailable; formatted Problems matchers will be limited" >&2
fi
raw_log="$(mktemp)"
trap 'rm -f "${raw_log}"' EXIT
status=0
xcodebuild "${args[@]}" "$@" "${action}" 2>&1 | tee "${raw_log}" | "${formatter[@]}" || status=$?
if [[ "${action}" == "test" ]] && grep -qE '^/.+:[0-9]+: error: ' "${raw_log}"; then
    echo
    echo "Failures:"
    grep -E '^/.+:[0-9]+: error: ' "${raw_log}" | sort -u
fi
exit "${status}"
