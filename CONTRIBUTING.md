# Contributing

Run the standard-library test suite with `python3 -m unittest discover -s tests -v`.
Shell syntax is checked by the tests. Changes to generated runtime files need
coverage for the actual copied scripts, not only the rendering functions.

Keep repository and worktree discovery separate. A hook can run with Git's
directory/index variables set; local Git queries must not use another
worktree's index. Preserve prior hooks and custom editor files. Do not run
network operations, installs, builds or indexing from the checkout hook.

New project-specific behavior belongs in the private JSON profile. Examples
should use synthetic project names. Do not include local profiles, generated
build-server files, test run artifacts, dependency checkouts or workstation
paths in this repository.

When changing regular-build flags, verify that `-derivedDataPath` is still
absent by default and that the debugger source map matches the chosen build
mode. Validate iOS attach changes on a concrete simulator. The optional real
Xcode smoke test is described in README.md.
