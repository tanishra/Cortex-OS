"""Orphan browser cleanup: kill Chromium procs leaked by a crashed worker.

Constraint: safe only with ONE task-worker process per profiles dir — a
sibling worker's live browsers share the same root and would be killed.
"""

import logging
import os
import re
import signal
import subprocess
from pathlib import Path

logger = logging.getLogger("cortex.orphans")

_USER_DATA_RE = re.compile(r"--user-data-dir[=\"']([^\"'\s]+)")


def _chromium_procs(profiles_root: Path) -> list[tuple[int, str]]:
    """(pid, profile_dir) for chromium procs using our profile dirs."""
    try:
        # ps shows full argv; pgrep -fl only prints the process name on macOS.
        out = subprocess.run(
            ["ps", "axo", "pid,args"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        logger.warning("ps failed; orphan scan skipped", exc_info=True)
        return []
    procs = []
    for line in out.splitlines():
        if "user-data-dir" not in line:
            continue
        m = _USER_DATA_RE.search(line)
        if not m:
            continue
        profile_dir = m.group(1)
        try:
            pid = int(line.split(None, 1)[0])
        except (IndexError, ValueError):
            continue
        if str(profiles_root) in profile_dir:
            procs.append((pid, profile_dir))
    return procs


def kill_orphan_browsers(profiles_root: Path, protected_dirs: set[str]) -> int:
    """Kill chromium procs on profile dirs not in `protected_dirs`.

    Protected = profile dirs owned by live sessions or tasks being resumed.
    Never raises — cleanup is best-effort.
    """
    killed = 0
    for pid, profile_dir in _chromium_procs(profiles_root):
        if Path(profile_dir).name in protected_dirs:
            continue
        try:
            os.kill(pid, signal.SIGKILL)
            killed += 1
            logger.info("Killed orphan browser pid=%d dir=%s", pid, profile_dir)
        except ProcessLookupError:
            pass
        except OSError:
            logger.warning("Failed to kill orphan pid=%d", pid, exc_info=True)
    return killed
