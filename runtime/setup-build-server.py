#!/usr/bin/env python3
"""Generate the build server's discovery file, preserving platform selection."""
import argparse
import subprocess
import sys
from editor_support import find_root, setup_server

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", nargs="?", help="configured platform, for example macos or ios")
    args = parser.parse_args()
    try:
        raise SystemExit(setup_server(find_root(), args.platform))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
