#!/bin/sh
# Explicit, pinned source build. The hook never calls this installer.
exec python3 "$(dirname "$0")/install_server.py" "$@"
