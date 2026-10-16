#!/usr/bin/env python3
"""Print the configured container's regular Xcode DerivedData directory."""
from editor_support import derived_data as configured_derived_data, find_root, load_worktree_config


def derived_data(root):
    """Keep the original one-argument helper usable by preserved local scripts."""
    return str(configured_derived_data(root, load_worktree_config(root)))

if __name__ == "__main__":
    root = find_root()
    print(derived_data(root))
