#!/usr/bin/env node
"use strict";

// Thin launcher: find a Python 3 interpreter, then hand the terminal to ninja.py.
// The game itself is pure-Python curses — Node only locates Python and spawns it.

const { spawnSync } = require("child_process");
const path = require("path");

const GAME = path.join(__dirname, "..", "ninja.py");

// Candidate interpreters, most-specific first. Windows ships "py -3".
const CANDIDATES =
  process.platform === "win32"
    ? [["py", ["-3"]], ["python", []], ["python3", []]]
    : [["python3", []], ["python", []]];

function resolvePython() {
  for (const [cmd, pre] of CANDIDATES) {
    const probe = spawnSync(cmd, [...pre, "-c", "import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)"], {
      stdio: "ignore",
    });
    if (!probe.error && probe.status === 0) return [cmd, pre];
  }
  return null;
}

const py = resolvePython();
if (!py) {
  console.error(
    [
      "cli-ninja-fight: Python 3 is required but was not found on your PATH.",
      "",
      "  macOS:   brew install python   (or use the system python3)",
      "  Linux:   sudo apt install python3   # or your distro's package",
      "  Windows: https://www.python.org/downloads/  (tick 'Add to PATH')",
      "",
      "The curses game needs a terminal — run it in a real terminal, not a pipe.",
    ].join("\n")
  );
  process.exit(1);
}

const [cmd, pre] = py;
// Inherit stdio so curses drives the real TTY. Pass through any extra args.
const run = spawnSync(cmd, [...pre, GAME, ...process.argv.slice(2)], {
  stdio: "inherit",
});

if (run.error) {
  console.error("cli-ninja-fight: failed to launch Python:", run.error.message);
  process.exit(1);
}
process.exit(run.status == null ? 1 : run.status);
