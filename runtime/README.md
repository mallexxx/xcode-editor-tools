# Generated local editor integration

These scripts use the private profile in `.build/xcode-editor/config.json`.
Their source is maintained by **xcode-editor-tools**, outside this worktree.
Change the shared profile or source harness, then run its `apply --all` command
to update files that have not been customized. Existing tracked files and
custom edits are preserved by the bootstrap.

- `setup-build-server.py [macos|ios]`: select the configured platform and write
  `buildServer.json`. Restart SourceKit-LSP after changing platforms.
- `xcodebuild.sh build SCHEME [DESTINATION] [ARGS...]`: build with Xcode's
  regular configuration and DerivedData location. `test` and the other
  standard build/test actions are accepted too.
- `simulator.sh [--build-only|--no-build|--test SCHEME] [--only-testing TARGET]
  [DEVICE]`: use the `ios` profile to build, test, or install and launch on a
  concrete simulator, waiting for lldb-dap.
- `install-build-server.sh`: explicitly build the pinned server from source.
- `index-in-background.py [--all] [--if-idle]`: run headless indexing.
- `background-indexing.sh install|uninstall|status`: manage optional launchd
  indexing. Installing the Git hook never installs this background job.

`XCODE_EDITOR_WORKTREE_CACHE=1` opts into shared compilation CAS with prefix
maps and `.build/xcodebuild`. Its debugger mappings are written to
`.build/debug.lldbinit`. Regular builds keep real source paths and share the
normal Xcode index/build location. Do not build the same worktree from Xcode
and a task simultaneously.

The generated `.code-workspace` file contains the tasks and debug launches.
Trust the workspace and allow its folder-open task in VS Code or Cursor.
Swift language support uses Xcode's selected toolchain and the pinned BSP
fork. `xcbeautify` is optional; it supplies formatted Problems output.

The wrapper prints the path to `.build/xcode-editor/xcodebuild.log` and keeps
the complete, unformatted xcodebuild stdout/stderr there, even on failure or
after a successful build followed by a debugger error. The next build/test
invocation replaces it; displaying `--help` leaves it intact. The file is
local, Git-ignored, and readable only by its owner.
