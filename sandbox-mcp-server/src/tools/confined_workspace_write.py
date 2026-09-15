"""Directory-descriptor writes for the sandbox's explicit workspace contract."""

from __future__ import annotations

import contextlib
import os
import secrets
import shutil
import stat
from pathlib import Path

CONTRACT = "directory-fd-write-v1"


def supported() -> bool:
    return (
        os.name == "posix"
        and hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and all(fn in os.supports_dir_fd for fn in (os.open, os.mkdir, os.rename, os.unlink))
    )


def workspace_mount_id(root: str) -> int | None:
    """Only a Linux mount root supplies the rename boundary this contract needs.

    The sandbox namespace must not grant callers CAP_SYS_ADMIN. A directory
    cannot be renamed out of this mount by an unprivileged sandbox process.
    Host administrators remain outside the sandbox threat boundary.
    """
    if not supported() or not Path("/proc/self/mountinfo").is_file():
        return None
    try:
        status = Path("/proc/self/status").read_text().splitlines()
        capabilities = next(line.split()[1] for line in status if line.startswith("CapBnd:"))
        if int(capabilities, 16) & (1 << 21):  # CAP_SYS_ADMIN permits mount changes.
            return None
        path = str(Path(root).resolve(strict=True))
        if path == "/":
            return None
        for line in Path("/proc/self/mountinfo").read_text().splitlines():
            fields = line.split()
            mount = fields[4]
            for escaped, literal in (
                (r"\040", " "),
                (r"\011", "\t"),
                (r"\012", "\n"),
                (r"\134", "\\"),
            ):
                mount = mount.replace(escaped, literal)
            if mount == path:
                return int(fields[0])
    except (OSError, ValueError, IndexError, StopIteration):
        return None
    return None


def _require_fd_mount(fd: int, expected: int) -> None:
    values = Path(f"/proc/self/fdinfo/{fd}").read_text().splitlines()
    if not any(line.split() == ["mnt_id:", str(expected)] for line in values):
        raise ValueError("Write directory crosses the workspace mount boundary")


def write_workspace_file(
    root: str,
    requested_path: str,
    content: str,
    mode: str,
    require_mount: bool = False,
) -> None:
    """Never follow a caller-controlled directory or destination symlink.

    Append also replaces the destination atomically, so it cannot mutate another
    path through an existing hard link. File contents are streamed into the new
    inode rather than loading an unbounded existing file into memory.
    """
    if not supported():
        raise RuntimeError("Directory-descriptor workspace writes are unavailable")
    mount_id = workspace_mount_id(root) if require_mount else None
    if require_mount and mount_id is None:
        raise ValueError("Workspace write requires an independent Linux mount root")
    workspace = Path(root).resolve(strict=True)
    requested = Path(os.path.expanduser(requested_path))
    if not requested.is_absolute():
        requested = workspace / requested
    try:
        parts = requested.relative_to(workspace).parts
    except ValueError as exc:
        raise ValueError("Write path is outside the workspace") from exc
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Write path is not a workspace file")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parent_fd = os.open(workspace, directory_flags)
    temporary: str | None = None
    source_fd: int | None = None
    try:
        if mount_id is not None:
            _require_fd_mount(parent_fd, mount_id)
        for component in parts[:-1]:
            with contextlib.suppress(FileExistsError):
                os.mkdir(component, mode=0o755, dir_fd=parent_fd)
            child_fd = os.open(component, directory_flags, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = child_fd
            if mount_id is not None:
                _require_fd_mount(parent_fd, mount_id)
        # Serialize atomic append/read-replace across threads and server processes.
        import fcntl

        fcntl.flock(parent_fd, fcntl.LOCK_EX)
        name = parts[-1]
        original_mode: int | None = None
        try:
            source_fd = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=parent_fd,
            )
        except FileNotFoundError:
            pass
        if source_fd is not None:
            source_stat = os.fstat(source_fd)
            if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_nlink != 1:
                raise ValueError("Write destination must be an single-link regular workspace file")
            original_mode = stat.S_IMODE(source_stat.st_mode)
        temporary = f".memstack-write-{secrets.token_hex(16)}"
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
        with os.fdopen(fd, "wb") as destination:
            if mode == "append" and source_fd is not None:
                with os.fdopen(os.dup(source_fd), "rb") as source:
                    shutil.copyfileobj(source, destination, length=64 * 1024)
            destination.write(content.encode("utf-8"))
            destination.flush()
            if original_mode is not None:
                os.fchmod(destination.fileno(), original_mode)
            os.fsync(destination.fileno())
        os.rename(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        temporary = None
        os.fsync(parent_fd)
    finally:
        if source_fd is not None:
            os.close(source_fd)
        if temporary is not None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=parent_fd)
        os.close(parent_fd)
