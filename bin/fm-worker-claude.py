#!/usr/bin/env python3
"""Launch a named Claude session with a native prompt-bar color.

Usage: fm-worker-claude.py <name> <orange|blue|red> -- <claude arguments...>
Initializes a fresh session with the local /color command in print mode, then
execs the interactive CLI on that same session. No terminal input injection,
settings-store edits, model request, or credential copying is needed.
The launch environment (including account selection) is preserved. Hooks and
MCP are disabled only for the local-command initializer, not for the worker.
"""

import os
import subprocess
import sys
import uuid


def main():
    args = sys.argv[1:]
    if args == ["--help"]:
        print(__doc__)
        return 0
    if len(args) < 3 or args[2] != "--" or args[1] not in ("orange", "blue", "red"):
        print("error: expected <name> <orange|blue|red> -- <claude arguments...>; run fm-worker-claude.py --help", file=sys.stderr)
        return 2
    name, color = args[:2]
    if not name or any(ord(c) < 32 or ord(c) == 127 for c in name):
        print("error: session name must be nonempty and contain no control characters; pass a display name", file=sys.stderr)
        return 2
    session = str(uuid.uuid4())
    seed = ["claude", "--print", "--setting-sources", "", "--settings",
            '{"disableAllHooks":true}', "--strict-mcp-config", "--mcp-config",
            '{"mcpServers":{}}', "--max-budget-usd", "0.000001", "--session-id", session, "--name", name,
            "/color " + color]
    try:
        result = subprocess.run(seed, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, timeout=30, check=False)
        if result.returncode != 0 or result.stdout.strip() != "Session color set to: " + color:
            print("error: Claude could not initialize the session color; worker not started. "
                  "Check `claude --version` and rerun the launch. " + result.stderr[-1000:], file=sys.stderr)
            return 1
        os.execvp("claude", ["claude", "--resume", session, "--name", name, *args[3:]])
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"error: Claude session initialization failed ({exc}); check `claude --version` and rerun the launch", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
