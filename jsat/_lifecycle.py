"""Safe process records for AI clients launched through JSAT."""
from __future__ import annotations

import json
import os
import signal
import time
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path

MANAGED_TOOLS = ("claude", "codex", "opencode")


@dataclass
class LifecycleRecord:
    """Minimal, non-sensitive state needed to manage one launched client."""

    tool: str
    via: str
    repo: str
    model: str | None = None
    pid: int | None = None
    process_token: str | None = None
    status: str = "exited"
    started_at: float = 0.0
    updated_at: float = 0.0
    exit_code: int | None = None


def runtime_dir() -> Path:
    """Return the global runtime directory, with explicit test/CI overrides."""
    explicit = os.environ.get("JSAT_RUNTIME_DIR", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    data_dir = os.environ.get("JSAT_DATA_DIR", "").strip()
    if data_dir:
        return Path(data_dir).expanduser().resolve() / "runtime"
    return Path.home() / ".jsat" / "runtime"


def _record_path(tool: str) -> Path:
    if tool not in MANAGED_TOOLS:
        raise ValueError(f"unsupported managed tool: {tool}")
    return runtime_dir() / f"{tool}.json"


def save_record(record: LifecycleRecord) -> None:
    """Atomically persist a lifecycle record with user-only permissions."""
    path = _record_path(record.tool)
    path.parent.mkdir(parents=True, exist_ok=True)
    record.updated_at = time.time()
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(asdict(record), indent=2) + "\n", encoding="utf-8")
    with suppress(OSError):
        temporary.chmod(0o600)
    temporary.replace(path)


def load_record(tool: str) -> LifecycleRecord | None:
    path = _record_path(tool)
    try:
        return LifecycleRecord(**json.loads(path.read_text(encoding="utf-8")))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def list_records() -> list[LifecycleRecord]:
    records = [record for tool in MANAGED_TOOLS if (record := load_record(tool))]
    return sorted(records, key=lambda item: item.updated_at, reverse=True)


def latest_record(*, running_only: bool = False) -> LifecycleRecord | None:
    for record in list_records():
        if not running_only or is_running(record):
            return record
    return None


def process_token(pid: int) -> str | None:
    """Return a PID-reuse-resistant process start token where the OS exposes one."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        fields = stat.rsplit(")", 1)[1].split()
        return f"linux:{fields[19]}"
    except (IndexError, OSError):
        pass
    try:
        import subprocess

        result = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=2,
        )
        started = result.stdout.strip()
        return f"ps:{started}" if result.returncode == 0 and started else None
    except (OSError, subprocess.SubprocessError):
        return None


def is_running(record: LifecycleRecord) -> bool:
    if not record.pid or record.pid <= 1:
        return False
    try:
        os.kill(record.pid, 0)
    except OSError:
        return False
    current_token = process_token(record.pid)
    return bool(record.process_token and current_token == record.process_token)


def _descendants(pid: int) -> list[int]:
    """Return Linux descendants of a managed process; other OSes safely return none."""
    found: list[int] = []
    pending = [pid]
    while pending:
        parent = pending.pop()
        try:
            children = Path(f"/proc/{parent}/task/{parent}/children").read_text().split()
        except OSError:
            continue
        child_pids = [int(child) for child in children if child.isdigit()]
        found.extend(child_pids)
        pending.extend(child_pids)
    return found


def stop_record(record: LifecycleRecord, *, force: bool = False, timeout: float = 5.0) -> bool:
    """Stop only a validated JSAT-owned process and its current descendants."""
    if not is_running(record):
        record.pid = None
        record.process_token = None
        record.status = "exited"
        save_record(record)
        return False

    assert record.pid is not None
    targets = [record.pid, *_descendants(record.pid)]
    for pid in targets:
        with suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_running(record):
            break
        time.sleep(0.1)

    if is_running(record):
        if not force:
            return False
        kill_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
        for pid in reversed(targets):
            with suppress(ProcessLookupError):
                os.kill(pid, kill_signal)

    record.pid = None
    record.process_token = None
    record.status = "stopped"
    save_record(record)
    return True


def run_foreground(command: list[str], record: LifecycleRecord) -> int:
    """Run a client in the foreground while maintaining its lifecycle record."""
    import subprocess

    process = subprocess.Popen(command, cwd=record.repo)
    record.pid = process.pid
    record.process_token = process_token(process.pid)
    record.status = "running"
    record.started_at = time.time()
    record.exit_code = None
    save_record(record)
    try:
        exit_code = process.wait()
    finally:
        current = load_record(record.tool)
        if current is not None and current.pid == process.pid:
            current.exit_code = process.poll()
            if current.exit_code is None:
                current.status = "running"
            else:
                current.pid = None
                current.process_token = None
                current.status = "exited"
            save_record(current)
    return exit_code
