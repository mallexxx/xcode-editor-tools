#!/usr/bin/env python3
"""Build the configured BSP revision and install its co-located resources."""
import argparse
import datetime
from pathlib import Path
import shutil
import subprocess
import tempfile

try:
    from .editor_support import find_root, git_environment, load_worktree_config, normalize_config
except ImportError:
    from editor_support import find_root, git_environment, load_worktree_config, normalize_config


def install(config):
    config = normalize_config(config)
    spec = config["build_server"]
    requested = Path(spec["install_dir"]).expanduser()
    if requested.is_symlink():
        raise ValueError("Refusing to replace a symlinked build-server installation")
    destination = requested.resolve()
    if destination.exists() and not all((destination / name).is_file() for name in ("sourcekit-xcode-bsp", "SWBBuildServiceBundle")):
        raise ValueError(f"Refusing to replace a directory that is not a build-server installation: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="xcode-editor-server-") as directory:
        source = Path(directory) / "source"
        subprocess.run(["git", "clone", "--quiet", "--", spec["repository"], str(source)], check=True, env=git_environment())
        subprocess.run(["git", "-C", str(source), "checkout", "--quiet", "--detach", spec["revision"]], check=True, env=git_environment())
        revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True, env=git_environment()).strip()
        if revision.lower() != spec["revision"].lower() or not (source / "Package.resolved").is_file():
            raise ValueError("The pinned source must contain a committed Package.resolved")
        build = ["xcrun", "swift", "build", "--package-path", str(source), "--configuration", "release", "--force-resolved-versions"]
        subprocess.run(build, check=True)
        products = Path(subprocess.check_output(build + ["--show-bin-path"], text=True).strip())
        # Stage on the destination filesystem; rename leaves running binaries intact.
        with tempfile.TemporaryDirectory(prefix=".xcode-editor-install-", dir=destination.parent) as staging_dir:
            staging = Path(staging_dir) / "installation"
            staging.mkdir()
            for name in ("sourcekit-xcode-bsp", "SWBBuildServiceBundle"):
                shutil.copy2(products / name, staging / name)
            for bundle in products.glob("*.bundle"):
                shutil.copytree(bundle, staging / bundle.name)
            (staging / "revision").write_text(revision + "\n")
            backup = None
            if destination.exists():
                stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                backup = destination.with_name(destination.name + ".previous-" + stamp)
                destination.rename(backup)
            try:
                staging.rename(destination)
            except OSError:
                if backup:
                    backup.rename(destination)
                raise
    print(f"Installed {destination / 'sourcekit-xcode-bsp'} at {revision}")
    if backup:
        print(f"Previous installation retained at {backup}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    install(load_worktree_config(find_root()))
