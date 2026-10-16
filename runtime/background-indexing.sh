#!/bin/sh
# Optional launchd agent; never installed by repository bootstrapping.
exec python3 "$(dirname "$0")/manage_background.py" "$@"
