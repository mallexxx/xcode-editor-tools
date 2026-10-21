# Repository profile

The private profile lives at `<git-common-dir>/xcode-editor/config.json`.
All project and generated-file paths below are relative to a worktree root;
absolute paths and parent traversal are rejected. Installation destinations
are the exception and can use `~` for the current user's home directory.

Use [minimal.json](examples/minimal.json) or
[two-platform.json](examples/two-platform.json) as input to `init --config`.

| Field | Meaning / default |
|---|---|
| `schema_version` | `1` |
| `container` | Required `.xcworkspace` or `.xcodeproj` path |
| `workspace_file` | Root editor workspace file; defaults to `<container-stem>.code-workspace` |
| `scripts_dir` | Generated runtime directory; defaults to `scripts/vscode` |
| `configuration` | Xcode/BSP build configuration; defaults to `Debug` |
| `default_platform` | Initial platform for a new worktree; otherwise existing selection is preserved |
| `profiles` | Configured `macos` and/or `ios` platform profiles |
| `build_arguments` | Extra xcodebuild arguments; defaults to `-skipPackagePluginValidation`, `-skipMacroValidation` |
| `build_settings` | Optional BSP build-setting overrides |
| `editor_settings` | Extra/overridden VS Code workspace settings |
| `state_manifest` | Ownership data; defaults to `.build/xcode-editor/files.json` |
| `background_label` | Optional launchd label; default is a stable, per-repository name |

In `editor_settings["window.title"]`, `${worktreeName}` is replaced with the
worktree directory name during generation. VS Code title variables remain
unchanged. For example, `${worktreeName}${separator}${rootNameShort}` shows
the worktree name even when no editor is open.

Validation-skip flags are configurable. Use them only for plugins/macros you
trust; remove them from `build_arguments` when normal Xcode validation is wanted.

Each platform profile supports:

| Field | Meaning |
|---|---|
| `scheme` | Build/run scheme; defaults to the container stem |
| `sdk` | BSP SDK, default `macosx` or `iphonesimulator` |
| `label` | Display label, default `macOS` or `iOS` |
| `schemes` | Optional macOS scheme-picker entries |
| `scheme_input_id` | Optional macOS scheme-picker input ID; defaults to `scheme_macos` |
| `test_scheme` | Optional test scheme |
| `test_target` | Optional default `-only-testing` input |
| `test_input_id` | Optional test prompt input ID; defaults to `onlyTesting` for macOS or `onlyTestingIOS` for iOS |
| `app_path` | App product path relative to `.build/products`, e.g. `Debug/Example.app` |
| `executable` | macOS executable relative to the app, e.g. `Contents/MacOS/Example` |
| `device_prefix` | iOS simulator preference, default `iPhone` |
| `targets.include` | BSP regexes matched against `<project>/<target>` |
| `targets.exclude` | BSP regexes excluding target variants |
| `exclude_projects` | Project names to exclude from BSP indexing |
| `exclude_package_directories` | Directories containing other-platform local packages; names are discovered per worktree |

An empty include list selects every target. Large workspaces often contain
variants writing the same products into identical paths. Configure target
filters to select a coherent platform/variant, then check with the BSP's
`list-targets` command. Dependencies are included by the build service.

The server pin is configurable as an object:

```json
{
  "build_server": {
    "repository": "https://github.com/mallexxx/sourcekit-xcode-bsp.git",
    "revision": "afd0e3dd026b3ee3619e2271809debee25fec96f",
    "install_dir": "~/.local/opt/sourcekit-xcode-bsp"
  }
}
```

The default pin supplies target selection, Debug configuration, per-target
Swift arguments caching and Xcode's index layout. A replacement must support
those configuration fields and contain a committed `Package.resolved`. The
installer requires a full commit SHA, uses `--force-resolved-versions`, stages
the executable/service/resources together and retains a previous installation
instead of overwriting running binaries. Installation is explicit and may
take several minutes.

`SOURCEKIT_XCODE_BSP` overrides the server executable. The server executable
must remain beside its compatible service executable and resource bundles.
The harness does not globally set `XCBBUILDSERVICE_PATH` for regular builds.

## Existing integrations

To adopt a previous ownership manifest, set `state_manifest` to its relative
path. Only files matching their recorded hash are eligible for replacement.
Do not use an untrusted ownership manifest.

An optional `compatibility` object lets a private profile retain earlier
environment variable names without putting project-specific names in the
source:

```json
{
  "compatibility": {
    "worktree_cache_environment": "MY_OLD_CACHE_FLAG",
    "background_indexer_environment": "MY_OLD_INDEXER_FLAG"
  }
}
```

`install --adopt-hook-sha256 HASH` suppresses forwarding of an earlier
post-checkout hook only when its current content matches that exact SHA-256.
Use it when migrating a hook that already performs this same bootstrap;
otherwise the default is to chain the previous hook. A mismatched hash stops
installation. Existing hook files are not deleted.

One shared profile describes one Git repository. Branches missing its selected
container are skipped. If branches deliberately use different container paths,
update the profile before applying it; the tool does not guess a substitute.
