"""Linux /proc filesystem parser providing read-only system and process telemetry."""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from self_healing.core.models import ProcessState
from self_healing.logging.logger import get_logger

logger = get_logger("monitoring.proc")


def parse_proc_uptime(proc_path: Path = Path("/proc/uptime")) -> Tuple[float, float]:
    """Read system uptime and idle time from /proc/uptime.
    
    Returns:
        Tuple of (uptime_seconds, cumulative_idle_seconds).
    """
    try:
        content = proc_path.read_text().strip()
        parts = content.split()
        if len(parts) >= 2:
            return float(parts[0]), float(parts[1])
        elif len(parts) == 1:
            return float(parts[0]), 0.0
    except (FileNotFoundError, PermissionError, ValueError) as e:
        logger.debug("Failed to read %s: %s", proc_path, e)
    return 0.0, 0.0


def parse_proc_loadavg(proc_path: Path = Path("/proc/loadavg")) -> Tuple[float, float, float]:
    """Read 1-minute, 5-minute, and 15-minute load averages from /proc/loadavg.
    
    Returns:
        Tuple of (load_1m, load_5m, load_15m).
    """
    try:
        content = proc_path.read_text().strip()
        parts = content.split()
        if len(parts) >= 3:
            return float(parts[0]), float(parts[1]), float(parts[2])
    except (FileNotFoundError, PermissionError, ValueError) as e:
        logger.debug("Failed to read %s: %s", proc_path, e)
    return 0.0, 0.0, 0.0


def parse_proc_meminfo(proc_path: Path = Path("/proc/meminfo")) -> Dict[str, int]:
    """Parse /proc/meminfo into a dictionary with byte values.
    
    Returns:
        Dict mapping metric key (e.g., 'MemTotal', 'Buffers', 'Cached') to bytes (int).
    """
    result: Dict[str, int] = {}
    try:
        lines = proc_path.read_text().splitlines()
        for line in lines:
            if ":" not in line:
                continue
            key, val_str = line.split(":", 1)
            key = key.strip()
            parts = val_str.strip().split()
            if not parts:
                continue
            try:
                num = int(parts[0])
                # Linux /proc/meminfo values are typically in kB
                if len(parts) > 1 and parts[1].lower() == "kb":
                    num *= 1024
                result[key] = num
            except ValueError:
                continue
    except (FileNotFoundError, PermissionError) as e:
        logger.debug("Failed to read %s: %s", proc_path, e)
    return result


def parse_proc_stat(proc_path: Path = Path("/proc/stat")) -> Dict[str, int]:
    """Parse scheduler counters from /proc/stat.
    
    Extracts ctxt, processes, procs_running, procs_blocked, and btime.
    
    Returns:
        Dict of metric names to integer counts.
    """
    metrics: Dict[str, int] = {}
    target_keys = {"ctxt", "processes", "procs_running", "procs_blocked", "btime"}
    try:
        lines = proc_path.read_text().splitlines()
        for line in lines:
            parts = line.strip().split()
            if not parts:
                continue
            key = parts[0]
            if key in target_keys and len(parts) >= 2:
                try:
                    metrics[key] = int(parts[1])
                except ValueError:
                    pass
    except (FileNotFoundError, PermissionError) as e:
        logger.debug("Failed to read %s: %s", proc_path, e)
    return metrics


def parse_proc_pid_status(pid: int, proc_root: Path = Path("/proc")) -> Dict[str, str]:
    """Parse /proc/[pid]/status into a dictionary of string key-value pairs.
    
    Returns:
        Dict of status fields or empty dict if process not found/inaccessible.
    """
    status_file = proc_root / str(pid) / "status"
    result: Dict[str, str] = {}
    try:
        lines = status_file.read_text().splitlines()
        for line in lines:
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            result[key.strip()] = val.strip()
    except (FileNotFoundError, PermissionError, ProcessLookupError) as e:
        logger.debug("Failed to read status for PID %s: %s", pid, e)
    return result


def parse_proc_pid_cmdline(pid: int, proc_root: Path = Path("/proc")) -> List[str]:
    """Read command line arguments from /proc/[pid]/cmdline (null-byte separated).
    
    Returns:
        List of command line argument strings.
    """
    cmdline_file = proc_root / str(pid) / "cmdline"
    try:
        data = cmdline_file.read_bytes()
        if not data:
            return []
        parts = data.split(b"\x00")
        return [p.decode("utf-8", errors="replace") for p in parts if p]
    except (FileNotFoundError, PermissionError, ProcessLookupError) as e:
        logger.debug("Failed to read cmdline for PID %s: %s", pid, e)
    return []


def map_proc_state_to_enum(state_str: str) -> ProcessState:
    """Map Linux process state character or status string to ProcessState enum.
    
    Common Linux state characters:
      R: Running
      S: Sleeping (interruptible wait)
      D: Disk sleep (uninterruptible wait)
      T / t: Stopped
      Z: Zombie
      X: Dead
      I: Idle
    """
    if not state_str:
        return ProcessState.UNKNOWN

    first_char = state_str[0].upper()
    mapping = {
        "R": ProcessState.RUNNING,
        "S": ProcessState.SLEEPING,
        "D": ProcessState.DISK_SLEEP,
        "T": ProcessState.STOPPED,
        "Z": ProcessState.ZOMBIE,
        "X": ProcessState.DEAD,
        "I": ProcessState.IDLE,
    }
    return mapping.get(first_char, ProcessState.UNKNOWN)
