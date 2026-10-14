"""Restricted file/backup operations, executed inside an isolated container.

The control plane passes one JSON object on stdin. User paths are always relative
to /workspace. No user input becomes a host path or host shell command.
"""

import base64
import io
import json
import os
import shutil
import sys
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path("/workspace")
MAX_FILE = 64 * 1024
MAX_FILES = 2000
MAX_BACKUP = 20 * 1024 * 1024
MAX_EXPANDED = 50 * 1024 * 1024


def safe_path(value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\x00" in value:
        raise ValueError("Use a relative file path without '..'.")
    target = ROOT / path
    for part in [target, *target.parents]:
        if part == ROOT:
            break
        if part.is_symlink():
            raise ValueError("Symbolic links cannot be edited or restored.")
    if target == ROOT or not target.resolve().is_relative_to(ROOT):
        raise ValueError("Path must name a file inside the workspace.")
    return target


def files():
    result = []
    for parent, dirs, names in os.walk(ROOT, followlinks=False):
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in {"node_modules", ".git", ".venv", "__pycache__"}
            and not (Path(parent) / d).is_symlink()
        )
        for name in sorted(names):
            path = Path(parent) / name
            if path.is_symlink() or not path.is_file():
                continue
            result.append({"path": str(path.relative_to(ROOT)), "size": path.stat().st_size})
            if len(result) >= MAX_FILES:
                return {"files": result, "truncated": True}
    return {"files": result, "truncated": False}


def snapshot():
    output, total, count = io.BytesIO(), 0, 0
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for parent, dirs, names in os.walk(ROOT, followlinks=False):
            dirs[:] = sorted(dirs)
            for name in sorted(dirs) + sorted(names):
                path = Path(parent) / name
                if path.is_symlink():
                    raise ValueError("Remove symbolic links before creating a backup.")
                if not path.is_file() and not path.is_dir():
                    raise ValueError("Backups support regular files and directories only.")
                total += path.stat().st_size if path.is_file() else 0
                count += 1
                if total > MAX_EXPANDED or count > MAX_FILES:
                    raise ValueError("Backup limit: 50 MiB of files and 2,000 entries.")
                archive.add(path, arcname=str(path.relative_to(ROOT)), recursive=False)
    if output.tell() > MAX_BACKUP:
        raise ValueError("Compressed backup exceeds 20 MiB.")
    return {"archive": base64.b64encode(output.getvalue()).decode()}


def restore(encoded):
    raw = base64.b64decode(encoded, validate=True)
    if len(raw) > MAX_BACKUP:
        raise ValueError("Backup exceeds 20 MiB.")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        members, total, seen = [], 0, set()
        for member in archive:
            target = safe_path(member.name)
            if not (member.isfile() or member.isdir()) or member.name in seen:
                raise ValueError("Unsafe or duplicate archive member.")
            seen.add(member.name)
            total += member.size
            members.append((member, target))
            if len(members) > MAX_FILES or total > MAX_EXPANDED:
                raise ValueError("Archive exceeds extraction limits.")
        # Validate every path and type before changing existing files.
        file_paths = {str(target) for member, target in members if member.isfile()}
        for _, target in members:
            if any(str(parent) in file_paths for parent in target.parents):
                raise ValueError("Conflicting archive paths.")
        for path in ROOT.iterdir():
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
        for member, target in members:
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                target.chmod(member.mode & 0o777 & ~0o022)
    return {"restored": True}


def main(request):
    action = request["action"]
    if action == "list":
        return files()
    if action == "snapshot":
        return snapshot()
    if action == "restore":
        return restore(request["archive"])
    path = safe_path(request["path"])
    if action == "read":
        with path.open("rb") as stream:
            data = stream.read(MAX_FILE + 1)
        if len(data) > MAX_FILE:
            raise ValueError("The editor supports text files up to 64 KiB.")
        return {"path": request["path"], "content": data.decode("utf-8")}
    if action == "write":
        data = request["content"].encode("utf-8")
        if len(data) > MAX_FILE:
            raise ValueError("The editor supports text files up to 64 KiB.")
        path.parent.mkdir(parents=True, exist_ok=True)
        # O_NOFOLLOW closes the final-component symlink race. Operations stay
        # inside the container even if a terminal concurrently changes parents.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_NONBLOCK, 0o644)
        import stat

        with os.fdopen(fd, "wb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("Only regular text files can be edited.")
            stream.write(data)
        return {"saved": True}
    if action == "delete":
        if not path.is_file():
            raise ValueError("Only individual files can be deleted.")
        path.unlink()
        return {"deleted": True}
    raise ValueError("Unknown operation.")


if __name__ == "__main__":
    try:
        request = json.loads(sys.stdin.buffer.readline(30 * 1024 * 1024))
        print(json.dumps(main(request)))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)
