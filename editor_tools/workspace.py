"""Render VS Code tasks from project configuration, not a particular app."""
import copy
import json
from pathlib import Path


def problem_matchers(test=False):
    if test:
        return [{"owner": "xcodebuild", "fileLocation": "absolute", "severity": "error", "pattern": {
            "regexp": r"^(/.*?):(\d+): error: (.*)$", "file": 1, "line": 2, "message": 3,
        }}]
    return [
        {"owner": "xcodebuild", "fileLocation": "absolute", "severity": severity, "pattern": {
            "regexp": rf"^\[{symbol}\]\s+(/.*?):(\d+):(?:(\d+):)? (.*)$",
            "file": 1, "line": 2, "column": 3, "message": 4,
        }} for symbol, severity in [("x", "error"), ("!", "warning")]
    ]


def render_workspace(config, root=None):
    scripts = "${workspaceFolder}/" + config["scripts_dir"]
    settings = {
        "swift.path": "/usr/bin",
        "swift.sourcekit-lsp.backgroundIndexing": "on",
        "swift.debugger.debugAdapter": "lldb-dap",
        "swift.disableSwiftPackageManagerIntegration": True,
        "swift.searchSubfoldersForPackages": False,
        "swift.autoGenerateLaunchConfigurations": False,
        "files.exclude": {"**/.build": True},
        "files.watcherExclude": {"**/.build/**": True, "**/node_modules/**": True},
        "search.exclude": {"**/.build": True, "**/node_modules": True},
    }
    settings.update(copy.deepcopy(config.get("editor_settings", {})))
    tasks = [{
        "label": "Generate buildServer.json", "type": "process",
        "command": scripts + "/setup-build-server.py",
        "runOptions": {"runOn": "folderOpen"},
        "presentation": {"reveal": "silent"}, "problemMatcher": [],
    }]
    inputs = []
    launches = []
    debug_path = str(Path(root) / ".build/debug.lldbinit") if root else "${workspaceFolder}/.build/debug.lldbinit"
    debugger = ["command source -s 1 -e 0 " + json.dumps(debug_path)]
    for name, profile in config["profiles"].items():
        scheme = profile["scheme"]
        if name == "macos":
            build_label = f"Build {scheme}"
            tasks.append({
                "label": build_label, "type": "process", "command": scripts + "/xcodebuild.sh",
                "args": ["build", scheme],
                "group": {"kind": "build", "isDefault": name == config["default_platform"]},
                "problemMatcher": problem_matchers(),
            })
            if len(profile.get("schemes", [])) > 1:
                input_id = profile.get("scheme_input_id", f"scheme_{name}")
                inputs.append({"id": input_id, "type": "pickString", "description": "Scheme",
                               "options": profile["schemes"], "default": scheme})
                tasks.append({
                    "label": f"Build {profile['label']} scheme…", "type": "process",
                    "command": scripts + "/xcodebuild.sh", "args": ["build", "${input:" + input_id + "}"],
                    "group": "build", "problemMatcher": problem_matchers(),
                })
            if profile.get("app_path"):
                app = "${workspaceFolder}/.build/products/" + profile["app_path"]
                executable = profile.get("executable", "Contents/MacOS/" + profile["app_path"].split("/")[-1].removesuffix(".app"))
                launch = {"name": scheme, "type": "swift", "request": "launch",
                          "program": app + "/" + executable, "cwd": "${workspaceFolder}",
                          "initCommands": debugger}
                launches.append({**launch, "preLaunchTask": build_label})
                launches.append({**launch, "name": scheme + " (no build)"})
        else:
            tasks += [
                {"label": f"Build {scheme} (Simulator)", "type": "process",
                 "command": scripts + "/simulator.sh", "args": ["--build-only"],
                 "group": {"kind": "build", "isDefault": name == config["default_platform"]},
                 "problemMatcher": problem_matchers()},
                {"label": f"Run {scheme} on Simulator", "type": "process",
                 "command": scripts + "/simulator.sh", "problemMatcher": problem_matchers()},
            ]
            if profile.get("app_path"):
                attach_path = str(Path(root) / ".build/simulator-attach.lldb") if root else "${workspaceFolder}/.build/simulator-attach.lldb"
                launches.append({
                    "name": f"{scheme} (Simulator)", "type": "swift", "request": "attach",
                    "attachCommands": ["command source " + json.dumps(attach_path)],
                    "preLaunchTask": f"Run {scheme} on Simulator", "initCommands": debugger,
                })
        if profile.get("test_scheme"):
            args = ["test", profile["test_scheme"], "macOS"] if name == "macos" else ["--test", profile["test_scheme"]]
            if profile.get("test_target"):
                input_id = profile.get("test_input_id", "onlyTesting" if name == "macos" else "onlyTestingIOS")
                inputs.append({"id": input_id, "type": "promptString", "description": "Tests: target[/class[/method]]",
                               "default": profile["test_target"]})
                if name == "ios":
                    args.extend(["--only-testing", "${input:" + input_id + "}"])
                else:
                    args.append("-only-testing:${input:" + input_id + "}")
            tasks.append({
                "label": f"Test {profile['test_scheme']}", "type": "process",
                "command": scripts + ("/xcodebuild.sh" if name == "macos" else "/simulator.sh"), "args": args,
                "group": {"kind": "test", "isDefault": True},
                "problemMatcher": problem_matchers()[:1] + problem_matchers(test=True),
            })
    return {
        "folders": [{"path": "."}], "settings": settings,
        "extensions": {"recommendations": ["swiftlang.swift-vscode"]},
        "tasks": {"version": "2.0.0", "tasks": tasks, "inputs": inputs},
        "launch": {"version": "0.2.0", "configurations": launches},
    }
