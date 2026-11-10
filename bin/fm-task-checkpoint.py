#!/usr/bin/env python3
"""Record or compare a stopped task's Git/index/file fingerprints, never contents.

Usage: fm-task-checkpoint.py capture|verify WORKTREE CHECKPOINT
Ignored files are neither read nor copied. Symlinks are fingerprinted as links.
This is a drift check, not a backup. A changed file refuses resume for review.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile


def git(root, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.check_output(["git", "-C", str(root), *args], env=env)


def capture(root):
    root = root.resolve(strict=True)
    top = Path(os.fsdecode(git(root, "rev-parse", "--show-toplevel").strip())).resolve()
    if root != top:
        raise ValueError("checkpoint requires the worktree root")
    paths = set(git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split(b"\0")) - {b""}
    files = {}
    for raw in sorted(paths):
        name = os.fsdecode(raw)
        path = root / name
        # Never traverse a symlink ancestor into another directory.
        if any(p.is_symlink() for p in path.parents if p != root and root in p.parents):
            raise ValueError("symlink ancestor in checkpoint")
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            files[name] = {"kind": "missing"}
            continue
        if stat.S_ISLNK(mode):
            data = os.fsencode(os.readlink(path))
        elif stat.S_ISREG(mode):
            data = path.read_bytes()
        else:
            raise ValueError("non-file entry needs explicit checkpoint handling")
        files[name] = {"mode": stat.S_IMODE(mode), "sha256": hashlib.sha256(data).hexdigest()}
    return {"version": 1, "worktree": str(root), "head": os.fsdecode(git(root, "rev-parse", "HEAD").strip()),
            "branch": os.fsdecode(git(root, "symbolic-ref", "--quiet", "--short", "HEAD").strip()) if git(root, "rev-parse", "--abbrev-ref", "HEAD").strip() != b"HEAD" else None,
            "index": hashlib.sha256(git(root, "ls-files", "--stage", "-z")).hexdigest(), "files": files}


def main():
    action, root, target = sys.argv[1:]
    target = Path(target)
    current = capture(Path(root))
    if action == "verify":
        if target.is_symlink() or json.loads(target.read_text()) != current:
            raise ValueError("checkpoint drift; work preserved, review before resume")
    elif action == "capture":
        fd, tmp = tempfile.mkstemp(prefix=target.name + ".", dir=target.parent)
        try:
            with os.fdopen(fd, "w") as out:
                json.dump(current, out, sort_keys=True)
                out.write("\n")
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    else:
        raise ValueError("expected capture or verify")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError):
        print("error: task checkpoint could not be captured or verified; preserve work and inspect locally", file=sys.stderr)
        sys.exit(1)
