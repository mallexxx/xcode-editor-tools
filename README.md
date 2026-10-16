# xcode-editor-tools

Use VS Code or Cursor with an existing Xcode project and its Git worktrees.
This harness generates local build-server configuration, build/test tasks,
macOS launches, and iOS simulator attach configurations. Xcode projects and
schemes remain the source of truth.

The source has no workstation paths or required workspace name. Project
details live in a private configuration inside Git's common directory.
Generated worktree files are self-contained; only the Git hook needs this
source checkout to remain available.

## Requirements

- macOS with Xcode 27 or newer selected through `xcode-select`. The pinned BSP
  revision is validated with Xcode 27.1 / Swift 6.4; recheck after Xcode updates.
- Python 3.11+ and a modern Git supporting `--path-format=absolute`.
- The [Swift editor extension](https://marketplace.visualstudio.com/items?itemName=swiftlang.swift-vscode)
  and workspace trust in VS Code/Cursor.
- A compatible [sourcekit-xcode-bsp](https://github.com/mallexxx/sourcekit-xcode-bsp)
  installation. The explicit installer builds a pinned commit with its
  committed dependency lockfile.
- Optional: `xcbeautify` for formatted build diagnostics in Problems.

The Python tooling uses only the standard library. Run it directly from this
checkout; a package manager, editor extension for this harness, or background
daemon is not required.

## Before the first setup

1. Clone this repository into a permanent directory:

   ```sh
   git clone https://github.com/mallexxx/xcode-editor-tools.git
   cd xcode-editor-tools
   ```

   Keep `xcode_editor.py`, `editor_tools/` and the complete `runtime/`
   directory together. There is no `pip install` step or Python requirements
   file.
2. Install the full Xcode application, open it once to finish its license and
   component setup, and select its developer directory. Command Line Tools
   alone are insufficient. If selection is needed, use
   `sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer`,
   adjusting the application path for your installation.
3. Ensure Python 3.11+ and Git are available on `PATH` in the terminal, Git
   hooks, and editor tasks. Check the selected tools:

   ```sh
   python3 --version
   git --version
   xcode-select -p
   xcodebuild -version
   xcrun --find swift
   xcrun --find sourcekit-lsp
   ```

4. Open the target project in Xcode, resolve its packages, configure signing,
   and confirm the intended scheme builds. Use schemes available from a new
   checkout; share them in Xcode if they currently exist only in user data.
   This harness uses the existing project and does not repair project build
   failures. The default configuration is `Debug`.
5. In VS Code or Cursor, install the **Swift** extension with identifier
   `swiftlang.swift-vscode` from the Extensions view. For iOS, install a
   compatible Simulator runtime through Xcode first.

The explicit server installer needs network access to the pinned public Git
repository and its Swift dependencies, along with space to compile them.
Your project's packages may have their own access requirements. Keep any
credentials in your normal Git/Xcode credential storage.

## First setup: macOS

Run these commands from this harness's source checkout. `Example`, its scheme
names and the paths below are placeholders: use your project's actual values.
`--app` names the built `.app` product, which may differ from the scheme.

```sh
cd /path/to/xcode-editor-tools
repo=/path/to/your/project-checkout

# Find available schemes; use -project for an .xcodeproj.
xcodebuild -list -workspace "$repo/Example.xcworkspace"

python3 xcode_editor.py init --repo "$repo" \
  --workspace Example.xcworkspace --scheme Example --app Example \
  --test-scheme 'Example Tests'
python3 xcode_editor.py install-server --repo "$repo"
python3 xcode_editor.py install --repo "$repo"
python3 xcode_editor.py apply --repo "$repo" --all
python3 xcode_editor.py status --repo "$repo"
```

Use `--project Example.xcodeproj` for a project without a separate workspace.
Omit the container argument only when the checkout has exactly one top-level
workspace, or exactly one top-level project and no separate workspace.
Nested containers can be configured explicitly. The default generated editor
filename follows the container name, for example `Example.code-workspace`.

Omit `--app` for projects without an application launch target. Omit
`--test-scheme` if no test task is needed. Projects with a different
configuration or product layout should use the JSON profile described below.
For a bare repository, pass its path as `--repo`; have at least one checked-out
worktree available for container discovery and initial verification.

`install-server` builds the full pinned commit and its locked dependencies;
it may take several minutes. It installs the server, build service and
resource bundles together. It is separate from the checkout hook, which
never installs software. To use an existing compatible installation, skip
this command and set `SOURCEKIT_XCODE_BSP` to its executable in both the
terminal and editor environment, or configure `build_server.install_dir`
before applying the profile. A stock upstream version may lack fields this
harness needs; see [CONFIGURATION.md](CONFIGURATION.md).

Open the generated `Example.code-workspace` file in VS Code/Cursor, trust it,
and allow its automatic folder-open task when prompted. The task refreshes
`buildServer.json`; the hook already generates it before the editor opens.
One indexing platform is selected per worktree. Initial preparation and
background indexing take time; inspect the Swift extension's Output channel
if code intelligence does not appear.

`init` creates a profile once and refuses to overwrite an existing one. For a
complete configuration, use `--config examples/two-platform.json` instead of
the discovery arguments, then edit that private profile for the real project.
The input example is copied, not linked.

## Verify the installation

From the configured application worktree, using the default paths:

```sh
cd /path/to/your/project-checkout
scripts/vscode/setup-build-server.py macos
"$HOME/.local/opt/sourcekit-xcode-bsp/sourcekit-xcode-bsp" list-targets
scripts/vscode/xcodebuild.sh build Example
git status --short
git check-ignore buildServer.json Example.code-workspace .vscode/settings.json
```

The setup command should succeed, `list-targets` marks selected roots with
`+`, and the build should succeed as it did in Xcode. Adjust the server path
for a custom installation. In a new integration the three generated paths
should be ignored, with no new tracked project changes. Existing unrelated
changes in your worktree remain visible in Git status.

In the editor, run **Tasks: Run Build Task**, run the configured test task,
and select the application in **Run and Debug**. Build once before using a
"no build" launch. Set a breakpoint in a source file and confirm it binds.
Use **Swift: Restart LSP Server** after changing the selected BSP platform.

To check future-worktree setup, create a worktree normally with
`git worktree add`, then inspect its generated `.code-workspace` and
`buildServer.json`. No second `init` is needed for worktrees sharing the
same Git common directory.

## iOS or combined macOS/iOS setup

For an iOS-only project, use `--platform ios` during the first initialization:

```sh
python3 xcode_editor.py init --repo /path/to/project \
  --workspace Example.xcworkspace --platform ios \
  --scheme 'Example iOS' --app Example
```

Then run the same `install-server`, `install` and `apply --all` commands as
above. For both platforms or target filtering, initialize a new integration
from the example instead:

```sh
python3 xcode_editor.py init --repo /path/to/project \
  --config examples/two-platform.json
```

Edit the resulting private `config.json` printed by `init`: replace the
example container, schemes, products and target regexes. Then install the
server/hook and apply the profile. For an already initialized integration,
edit that existing private profile and reapply instead of running `init`
again. Avoid editing the public example with private project details.

From a configured worktree:

```sh
scripts/vscode/setup-build-server.py ios
xcrun simctl list devices available
scripts/vscode/simulator.sh --build-only 'iPhone Example'
scripts/vscode/simulator.sh 'iPhone Example'
```

Replace the device name with one installed on your machine, or pass its UDID.
The generated simulator debug configuration runs this launcher and attaches
to the suspended application. Switch back with
`scripts/vscode/setup-build-server.py macos` only when a `macos` profile is
configured. Large workspaces should configure target filters before indexing
to avoid selecting conflicting variants; see [CONFIGURATION.md](CONFIGURATION.md).

## Configuration and file locations

Find the actual common directory with:

```sh
git -C /path/to/project rev-parse --path-format=absolute --git-common-dir
```

That works for ordinary repositories, bare repositories and linked worktrees.
The harness stores:

```text
<git-common-dir>/xcode-editor/
  config.json          private project profile
  installation.json    source checkout and previous hook configuration
  hooks/               managed forwarding hooks
<git-common-dir>/info/exclude
                       local ignore rules; tracked .gitignore is untouched

<worktree>/
  <container-name>.code-workspace
  buildServer.json
  .vscode/{settings,tasks,launch,extensions}.json
  scripts/vscode/       generated runtime scripts; directory is configurable
  .build/xcode-editor/{config,files}.json
                       runtime profile and ownership hashes
```

The default BSP installation is `~/.local/opt/sourcekit-xcode-bsp/`, shared
across worktrees. It is not vendored in this source repository.

```text
~/.local/opt/sourcekit-xcode-bsp/
  sourcekit-xcode-bsp
  SWBBuildServiceBundle
  *.bundle/             resources produced by the pinned Swift build
  revision              installed commit stamp
```

Keep these files together; copying only the server executable is insufficient.
The installer creates this layout. Ordinary builds also create
`.build/products` (a symlink to Xcode's products) and `.build/debug.lldbinit`;
simulator launches create `.build/simulator-attach.lldb`. These are runtime
outputs, not missing source files to copy into the harness repository.

See [CONFIGURATION.md](CONFIGURATION.md) for all profile fields, target filters,
dependency pins and compatibility settings. The same configuration applies
to registered worktrees wherever their checkout directories are located.

## Source files included

The repository contains everything needed to generate and maintain the local
integration. Keep the complete source tree when cloning or distributing it:

```text
xcode_editor.py                 CLI entry point
editor_tools/
  __init__.py                  harness version
  cli.py                       init/install/apply/status/removal commands
  repository.py                common-directory and worktree discovery
  bootstrap.py                 file generation, ownership and exclusions
  hooks.py                     hook installation, forwarding and removal
  workspace.py                 editor settings, tasks and launches
runtime/
  __init__.py                  Python package marker for source-side imports
  editor_support.py            shared configuration/BSP/DerivedData helpers
  setup-build-server.py         discovery-file generation
  sourcekit-xcode-bsp.sh        BSP launcher and indexer coordination
  xcode_derived_data.py         standalone DerivedData helper
  xcodebuild.sh                build/test wrapper
  simulator.sh                 simulator build/test/run/attach
  install-build-server.sh      standalone installer entry point
  install_server.py            pinned server/service/resource installation
  index-in-background.py       optional headless indexer
  background-indexing.sh       optional launchd entry point
  manage_background.py         launchd management
  README.md                    generated worktree usage guide
examples/{minimal,two-platform}.json
README.md                      full setup and troubleshooting
CONFIGURATION.md               all profile fields and migration options
CONTRIBUTING.md                development guidance
LICENSE                        harness MIT license
NOTICE.md                      separate dependency licensing
.gitignore                     local/artifact exclusions
.github/workflows/tests.yml    unit-test CI definition
tests/
  support.py                   isolated synthetic Git fixtures
  test_bootstrap.py            generation and hook tests
  test_runtime.py              copied-script behavior tests
  test_real_xcode.py           opt-in real Xcode smoke test
  fixtures/OrbitSample/
    project.yml                synthetic xcodegen project
    Sources/main.swift         unrelated sample application
```

`runtime/__init__.py` is used by the source-side Python package; generated
worktree scripts import their adjacent helper directly. The generator copies
the other runtime files, creates editor JSON from the profile, and records
ownership. No application project, real-project profile, patch snapshot,
prebuilt binary or dependency checkout is required in this source tree.

## Hooks and existing work

`install` writes its own shared hook directory and sets repository-local
`core.hooksPath`. It records the previous local/effective setting and forwards
existing executable hooks, preserving their arguments, working directory,
environment, standard streams and exit status. Default, absolute custom and
relative custom hook locations are supported. Relative hooks resolve against
the worktree where Git invokes the hook.

Only existing hooks and `post-checkout` receive dispatchers, so special Git
hooks such as `push-to-checkout` retain their default behavior when absent.
If you add another hook to the original hook directory later, rerun `install`
to register its dispatcher. Do not put custom hook source in the managed
directory.

`post-checkout` runs after a normal `git worktree add`, `git checkout` or
`git switch`. A file-only checkout is ignored. Bootstrap failures are printed
without turning a successful checkout into an error; failure from a prior
hook retains its original status.

Git does not invoke this hook for `worktree add --no-checkout`. Tools that
disable or bypass Git hooks, or a worktree-specific `core.hooksPath` override,
also need an explicit reconciliation:

```sh
python3 xcode_editor.py apply --repo /path/to/project --all
python3 xcode_editor.py apply --repo /path/to/project /path/to/worktree --dry-run
python3 xcode_editor.py status --repo /path/to/project
```

The bootstrap preserves tracked files, symlinks and files customized since its
last generated version. Owned, unchanged files can be refreshed when the
harness or profile changes. Existing tracked files cannot become ignored just
by adding exclude rules. Review reported conflicts; do not assume a preserved
old `buildServer.json` uses this server.

The explicit folder-open `setup-build-server.py` command refreshes the selected
discovery file even if it is tracked; avoid committing that machine-local
change. A clean new integration should leave `buildServer.json` untracked.

If the harness source checkout moves, rerun `install` from its new location.
If the target repository itself moves, rerun `install` and `apply --all` to
refresh local pointers. Generated runtime scripts do not import this source
checkout.

## Builds, tests and debugging

The task wrapper uses the configured workspace/project, scheme and build
configuration. Its regular mode deliberately omits `-derivedDataPath`, so
Xcode and command-line builds use matching parameters and the same default
DerivedData location. The helper honors Xcode's global custom DerivedData
root. Per-workspace custom location schemes beyond that are not inferred.

```sh
scripts/vscode/xcodebuild.sh build Example
scripts/vscode/xcodebuild.sh test 'Example Tests' macOS -only-testing:ExampleTests
```

Use the configured scripts directory if it differs from the default. For an
iOS profile, the simulator launcher prefers a booted device, then an available
device with the configured prefix. Tests also select a concrete simulator:

```sh
scripts/vscode/simulator.sh --test 'Example iOS Tests' --only-testing ExampleTests
```

The BSP's index uses Xcode's index layout and a separate preparation database.
Normal builds keep real debug paths. Do not run an Xcode build and a task build
against the same worktree concurrently.

Every wrapper build/test keeps complete, unformatted xcodebuild stdout/stderr
in `.build/xcode-editor/xcodebuild.log`, and prints that path in the terminal.
The log survives failed and successful builds, so it is still available if
the debugger fails afterwards. The next actual build/test invocation replaces
it; `--help` leaves it intact. It is Git-ignored and readable only by its owner.

## Optional compilation cache

```sh
XCODE_EDITOR_WORKTREE_CACHE=1 scripts/vscode/xcodebuild.sh build Example
```

This mode uses `.build/xcodebuild`, shared compilation CAS, and source/build
prefix maps. `.build/debug.lldbinit` maps those paths for debugging. It does
not share regular build products with Xcode. Regular-mode builds write an
LLDB init file without source maps.

This is compilation caching, not a package-resolution cache. Warm package
flags may be passed explicitly after successful resolution:

```sh
scripts/vscode/xcodebuild.sh build Example macOS \
  -skipPackageUpdates -onlyUsePackageVersionsFromResolvedFile
```

These flags do not eliminate package-graph evaluation. Keep mutable package
checkouts per worktree when branches can require different revisions.

## Optional background indexing

```sh
scripts/vscode/index-in-background.py --all --if-idle
scripts/vscode/background-indexing.sh install
scripts/vscode/background-indexing.sh status
scripts/vscode/background-indexing.sh uninstall
```

The optional launchd job runs every 30 minutes and skips while an editor is
open. Install it from a checkout that will remain available. The Git hook
never installs a launchd job, builds the server, indexes code, or accesses the
network. An editor's server stops a running headless indexer for that worktree.

## Removal

```sh
python3 xcode_editor.py uninstall --repo /path/to/project
```

This restores the previous repository-local hook configuration, or removes
our local override if there was none. Existing hooks remain untouched. Local
generated files, ownership data and exclude rules are retained for review and
reinstallation. Remove them manually if no longer wanted. The BSP installation
and optional launchd job have separate lifecycles.

## Troubleshooting

| Symptom | Check / action |
|---|---|
| Python import error or missing script | Keep the complete source tree together. Verify `python3 --version` is 3.11+ in the environment running Git/editor tasks. |
| Xcode points at Command Line Tools or has unfinished setup | Check `xcode-select -p` and `xcodebuild -version`; select the full Xcode application and finish its first launch. |
| `Configuration already exists` | Edit the private profile printed by `init`, then run `apply --all`; do not initialize it again. |
| Worktree reports `container missing` | Confirm the profile's relative `container` path exists on that branch. Branches without it are skipped. |
| No automatic worktree files | Run `status`; check `git config --show-origin --get core.hooksPath`. A `--no-checkout` creation, a worktree override, or disabled hooks needs an explicit `apply`. |
| A generated file is preserved or is still tracked | The bootstrap protects tracked/customized files. Merge the reported conflict manually; local ignore rules do not untrack existing files. |
| Build server missing or lacks target-selection support | Run `install-server` or select the configured compatible executable. Verify its `list-targets --help` succeeds. Keep the service and resource bundles alongside it. |
| No code intelligence | Open the generated workspace, trust it, allow its task, run `setup-build-server.py`, check the selected platform and Swift Output logs, then restart the LSP server. |
| Duplicate build outputs during indexing | Use the profile's include/exclude target filters to select a coherent platform/variant; inspect `list-targets` from that worktree. |
| App product not found or debugger cannot launch | Build once, inspect `.build/products`, and correct the profile's `configuration`, `app_path` and macOS `executable`. Debug paths are relative to the actual built product layout. |
| No available simulator | Install its runtime in Xcode, inspect `xcrun simctl list devices available`, and pass an available name/UDID. |
| Terminal works but editor cannot find tools/server | Match the editor task environment's `PATH`, selected Xcode and any `SOURCEKIT_XCODE_BSP` override to the terminal. |

For a build or post-build launch failure, inspect
`.build/xcode-editor/xcodebuild.log` before the next build. Debug-adapter
errors are separate: check the Swift/LLDB-DAP Output channels and Debug Console.

For a custom configuration such as `Development`, change both the top-level
`configuration` and the product paths in its profiles before applying. The
`--app` shortcut assumes the normal `Debug` or `Debug-iphonesimulator` layout.
Use the configuration reference for custom script directories, regex filters,
server pins and existing-hook migration.

## Public source and private files

Keep real-project settings in the target repository's Git common directory,
as `init` does. Its worktree copies contain real project names; generated BSP
and debugger files also contain absolute local paths. They belong to the
local integration and must not be copied into this public source tree.

The source examples and test fixtures use synthetic project names. The public
BSP fork URL and commit are intentional dependency references; its source and
build products are installed separately. No credentials are needed in a
harness profile.

The harness repository's `.gitignore` excludes bytecode, build products,
editor-generated files, environment files, logs and `/.local/` for private
draft configuration. Keep actual profiles and diagnostics out of public
examples and fixtures. Review the intended source-file set with:

```sh
git ls-files --cached --others --exclude-standard
git status --short
```

Publish reviewed source files through Git. If making an archive, use the same
reviewed file set: exclude `.git/`, ignored files, bytecode caches, generated
workspaces and runtime configuration. A recursive archive of a working
directory can include data that Git ignores. Previously tracked files also
remain tracked despite new ignore rules; review the intended diff before
publication.

## Development and verification

```sh
python3 -m unittest discover -s tests -v
```

Tests use synthetic Git repositories and worktrees in temporary directories.
They cover ordinary/bare layouts, external worktrees, existing/relative hooks,
hook removal, file ownership, custom settings, spaces/quotes in paths,
platform persistence, build arguments, exit status and debugger mappings.

For a real smoke test on macOS, install `xcodegen`, select Xcode and run:

```sh
XCODE_EDITOR_RUN_XCODE_TESTS=1 python3 -m unittest discover -s tests -p test_real_xcode.py -v
```

Set `SOURCEKIT_XCODE_BSP` to a compatible installed server to include target
discovery in that smoke test. The fixture is an unrelated minimal macOS app
named OrbitSample. This test does not use a developer's application repository.

The harness is MIT licensed; see [NOTICE.md](NOTICE.md) for separate components.
