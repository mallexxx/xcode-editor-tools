# Dependencies and provenance

The Python and shell harness in this repository is distributed under the MIT
license in `LICENSE`. It uses Python's standard library and commands supplied
by Git, macOS and Xcode. No third-party Python modules are vendored.

Code intelligence requires a separate
[sourcekit-xcode-bsp](https://github.com/slime-studio/sourcekit-xcode-bsp)
installation. The default source pin uses
[mallexxx/sourcekit-xcode-bsp](https://github.com/mallexxx/sourcekit-xcode-bsp),
whose target-selection, Debug configuration, compiler-argument caching and
Xcode index-layout changes are needed by this integration. That project and
its Swift dependencies retain their own licenses, including Apache 2.0.
Their source, patches, binaries and dependency checkouts are not included in
this harness repository.

`xcbeautify` and the Swift editor extension are separate software with their
own licenses. The Swift extension is required for the editor workflow;
`xcbeautify` is optional. Install them through their maintainers' documented
channels.
