"""
Append-only scheduler profiling logs (JSONL) for bottleneck analysis.

Each Django startup generates a unique RUN_CODE (e.g. run_20260430_110500) at
import time and writes to a dedicated file:
    <logs_dir>/scheduler_profile_<RUN_CODE>.jsonl

Settings (scheduler/scheduler/settings.py):
    SCHEDULER_PROFILE_LOG_DIR     - directory to store .jsonl files
                                    (default: BASE_DIR/logs)
    SCHEDULER_PROFILE_LOG_ENABLED - set to False / "0" to disable entirely

Disable at runtime:
    export SCHEDULER_PROFILE_LOG_ENABLED=0
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

# Generated once at Django startup (module import time).
RUN_CODE: str = datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S")

_lock = threading.Lock()
_tls = threading.local()

# Resolved lazily on first write so Django settings are available.
_resolved_path: Path | None = None
_resolved_path_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Correlation-id helpers (per-batch worker thread)
# ---------------------------------------------------------------------------

def set_profile_correlation_id(correlation_id: str | None) -> None:
    _tls.correlation_id = correlation_id


def clear_profile_correlation_id() -> None:
    if hasattr(_tls, "correlation_id"):
        delattr(_tls, "correlation_id")


def get_profile_correlation_id() -> str | None:
    return getattr(_tls, "correlation_id", None)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _profile_enabled() -> bool:
    try:
        from django.conf import settings
    except ImportError:
        return False
    return bool(getattr(settings, "SCHEDULER_PROFILE_LOG_ENABLED", True))


def _get_path() -> Path | None:
    """Return (and cache) the resolved .jsonl path for this run."""
    global _resolved_path
    if _resolved_path is not None:
        return _resolved_path
    with _resolved_path_lock:
        if _resolved_path is not None:
            return _resolved_path
        try:
            from django.conf import settings
        except ImportError:
            return None
        log_dir_raw = getattr(settings, "SCHEDULER_PROFILE_LOG_DIR", None)
        if not log_dir_raw:
            # Fall back: derive dir from old-style SCHEDULER_PROFILE_JSONL_PATH if set
            legacy = getattr(settings, "SCHEDULER_PROFILE_JSONL_PATH", None)
            if legacy:
                log_dir_raw = str(Path(legacy).parent)
            else:
                return None
        log_dir = Path(log_dir_raw)
        log_dir.mkdir(parents=True, exist_ok=True)
        _resolved_path = log_dir / f"scheduler_profile_{RUN_CODE}.jsonl"
        return _resolved_path


def _write_record(record: dict) -> None:
    if not _profile_enabled():
        return
    path = _get_path()
    if path is None:
        return
    line = json.dumps(record, default=str, separators=(",", ":")) + "\n"
    with _lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(line)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def persist_profile_row(label: str, elapsed_s: float | None = None, **fields) -> None:
    """Write one JSON object per call; safe from batch worker threads."""
    rec: dict = {"label": label, "run_code": RUN_CODE}
    if elapsed_s is not None:
        rec["elapsed_s"] = round(float(elapsed_s), 6)
    rec["ts_utc"] = datetime.now(timezone.utc).isoformat()
    cid = get_profile_correlation_id()
    if cid is not None:
        rec["correlation_id"] = cid
    for k, v in fields.items():
        if v is None:
            continue
        rec[k] = round(v, 6) if isinstance(v, float) else v
    _write_record(rec)
