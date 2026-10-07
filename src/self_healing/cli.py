"""Command-line interface and health-check command for self-healing framework."""

from pathlib import Path
import sys
from typing import Any, Dict
import click
import psutil

from self_healing import __version__
from self_healing.config.settings import get_default_config, load_config
from self_healing.core.models import utc_now
from self_healing.logging.logger import setup_logging
from self_healing.targets.registry import TargetRegistry


def run_system_health_checks() -> Dict[str, Any]:
    """Execute foundational user-space health checks."""
    checks: Dict[str, Any] = {}

    # 1. Python runtime check
    py_ok = sys.version_info >= (3, 10)
    checks["python_runtime"] = {
        "status": "PASS" if py_ok else "FAIL",
        "version": sys.version.split()[0],
        "detail": "Python >= 3.10 verified",
    }

    # 2. Linux /proc interfaces
    proc_files = ["/proc/version", "/proc/meminfo", "/proc/loadavg", "/proc/stat"]
    proc_ok = all(Path(p).is_file() for p in proc_files)
    checks["proc_filesystem"] = {
        "status": "PASS" if proc_ok else "FAIL",
        "checked": proc_files,
        "detail": "Kernel /proc observability available" if proc_ok else "Missing /proc files",
    }

    # 3. Systemd init check
    init_comm = Path("/proc/1/comm")
    systemd_ok = init_comm.exists() and "systemd" in init_comm.read_text().strip()
    checks["systemd_init"] = {
        "status": "PASS" if systemd_ok else "WARN",
        "detail": "systemd running as PID 1" if systemd_ok else "Non-systemd init or restricted container",
    }

    # 4. Host resource capacity
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    res_ok = mem.percent < 95.0 and disk.percent < 95.0
    checks["host_resources"] = {
        "status": "PASS" if res_ok else "WARN",
        "cpu_usage_pct": psutil.cpu_percent(interval=None),
        "ram_usage_pct": mem.percent,
        "disk_usage_pct": disk.percent,
    }

    # 5. Configuration validity
    try:
        cfg = load_config()
        registry = TargetRegistry(cfg.targets)
        checks["configuration"] = {
            "status": "PASS",
            "targets_count": len(registry.list_targets()),
            "dry_run": cfg.system.dry_run,
        }
    except Exception as e:
        checks["configuration"] = {
            "status": "FAIL",
            "error": str(e),
        }

    overall_healthy = all(
        c.get("status") in ("PASS", "WARN") for c in checks.values()
    )
    return {
        "healthy": overall_healthy,
        "timestamp": utc_now().isoformat(),
        "version": __version__,
        "checks": checks,
    }


@click.group()
@click.version_option(version=__version__)
def cli() -> None:
    """Autonomous Fault Detection and Self-Healing System for Linux."""
    pass


@cli.command("health")
@click.option("--json", "json_output", is_flag=True, help="Output health status as JSON.")
def health_cmd(json_output: bool) -> None:
    """Run environment and system health verification."""
    result = run_system_health_checks()
    healthy = result["healthy"]

    if json_output:
        import json
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo("==================================================")
        click.echo(f"  Linux Self-Healing Framework — Health Report")
        click.echo(f"  Version: {result['version']} | Timestamp: {result['timestamp']}")
        click.echo("==================================================")
        for name, data in result["checks"].items():
            status = data.get("status", "UNKNOWN")
            color = "green" if status == "PASS" else ("yellow" if status == "WARN" else "red")
            click.secho(f"[{status:4s}] {name:20s}", fg=color, nl=False)
            detail = data.get("detail") or data.get("error") or ""
            if detail:
                click.echo(f" : {detail}")
            else:
                click.echo()

        click.echo("--------------------------------------------------")
        if healthy:
            click.secho("OVERALL SYSTEM STATUS: HEALTHY", fg="green", bold=True)
        else:
            click.secho("OVERALL SYSTEM STATUS: DEGRADED / UNHEALTHY", fg="red", bold=True)

    sys.exit(0 if healthy else 1)


@cli.command("config")
@click.option("--path", "config_path", type=click.Path(exists=True), default=None, help="Path to config YAML file.")
def config_cmd(config_path: Optional[str]) -> None:
    """Validate and display system configuration."""
    try:
        cfg = load_config(config_path)
        click.secho("Configuration validated successfully:", fg="green")
        click.echo(f"  Mode: {cfg.system.mode}")
        click.echo(f"  Dry-Run Enforced: {cfg.system.dry_run}")
        click.echo(f"  Log Level: {cfg.system.log_level}")
        click.echo(f"  Sample Interval: {cfg.monitoring.sample_interval_seconds}s")
        click.echo(f"  Registered Targets: {len(cfg.targets)}")
        for t in cfg.targets:
            click.echo(f"    - {t.target_id} ({t.process_name}, prefix: {t.working_dir_prefix})")
    except Exception as e:
        click.secho(f"Configuration error: {e}", fg="red")
        sys.exit(1)


@cli.command("run")
@click.option("--dry-run/--no-dry-run", default=True, help="Operate in dry-run mode (default: True).")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None, help="Config file path.")
def run_cmd(dry_run: bool, config_path: Optional[str]) -> None:
    """Run the self-healing daemon (Skeleton Mode in Phase 1)."""
    cfg = load_config(config_path)
    cfg.system.dry_run = dry_run
    setup_logging(log_level=cfg.system.log_level)

    click.secho("==================================================", fg="cyan")
    click.secho(f"Starting Linux Self-Healing Daemon (Phase 1 Skeleton)", fg="cyan", bold=True)
    click.secho(f"Mode: {cfg.system.mode} | Dry-Run: {cfg.system.dry_run}", fg="yellow")
    click.secho("==================================================", fg="cyan")
    click.echo("Skeleton initialized. Complex healing loop deferred to future phases.")


def format_bytes(n_bytes: int) -> str:
    """Format bytes into human-readable string."""
    val = float(n_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(val) < 1024.0:
            return f"{val:3.1f} {unit}"
        val /= 1024.0
    return f"{val:.1f} PB"


def format_uptime(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, sec = divmod(rem, 60)
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if sec > 0 or not parts:
        parts.append(f"{sec}s")
    return " ".join(parts)


@cli.command("monitor")
@click.option("--json", "json_output", is_flag=True, help="Output snapshot as normalized JSON.")
@click.option("--target", "target_id", default=None, help="Filter telemetry to specific target ID.")
@click.option("--service", "service_names", multiple=True, help="Systemd service unit(s) to inspect.")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None, help="Config file path.")
def monitor_cmd(
    json_output: bool,
    target_id: Optional[str],
    service_names: tuple,
    config_path: Optional[str],
) -> None:
    """Capture and display a snapshot of the monitored Linux system."""
    from self_healing.monitoring.collector import SystemMetricsCollector

    try:
        cfg = load_config(config_path)
    except Exception:
        cfg = get_default_config()

    collector = SystemMetricsCollector()

    targets = cfg.targets
    if target_id:
        targets = [t for t in targets if t.target_id == target_id]

    services_to_check = list(service_names) if service_names else ["systemd-journald", "cron"]

    snapshot = collector.collect_system_snapshot(
        services=services_to_check,
        targets=targets,
    )

    if json_output:
        click.echo(snapshot.model_dump_json(indent=2))
        return

    # Header
    click.echo("================================================================================")
    click.secho("  LINUX SYSTEM TELEMETRY SNAPSHOT (READ-ONLY MONITOR)", fg="cyan", bold=True)
    click.echo(f"  Timestamp : {snapshot.timestamp.isoformat()}")
    click.echo(f"  Uptime    : {format_uptime(snapshot.uptime_seconds)} ({snapshot.uptime_seconds:.1f}s)")
    if snapshot.idle_seconds:
        click.echo(f"  Idle Time : {format_uptime(snapshot.idle_seconds)}")
    click.echo("================================================================================")

    # 1. CPU & Scheduler
    cpu = snapshot.cpu
    load_str = f"{cpu.load_1m or 0:.2f}, {cpu.load_5m or 0:.2f}, {cpu.load_15m or 0:.2f}"
    click.secho("[CPU & SCHEDULER]", fg="green", bold=True)
    click.echo(f"  Global CPU Usage : {cpu.percent:5.1f}%")
    if cpu.per_cpu_percent:
        cores_str = ", ".join(f"C{i}:{pct:.1f}%" for i, pct in enumerate(cpu.per_cpu_percent))
        click.echo(f"  Per-Core CPU     : {cores_str}")
    click.echo(f"  Load Averages    : {load_str} (1m, 5m, 15m)")
    if cpu.context_switches is not None:
        click.echo(f"  Context Switches : {cpu.context_switches:,}")
    if cpu.procs_running is not None:
        click.echo(f"  Processes        : {cpu.procs_running} running, {cpu.procs_blocked or 0} blocked")
    click.echo()

    # 2. Memory & Swap
    mem = snapshot.memory
    click.secho("[MEMORY & SWAP]", fg="green", bold=True)
    click.echo(
        f"  RAM Usage        : {mem.percent:5.1f}% "
        f"({format_bytes(mem.used_bytes)} / {format_bytes(mem.total_bytes)})"
    )
    click.echo(f"  RAM Available    : {format_bytes(mem.available_bytes)} (Free: {format_bytes(mem.free_bytes)})")
    if mem.buffers_bytes is not None or mem.cached_bytes is not None:
        buf_str = format_bytes(mem.buffers_bytes or 0)
        cache_str = format_bytes(mem.cached_bytes or 0)
        click.echo(f"  Buffers / Cached : {buf_str} / {cache_str}")
    if mem.swap_total_bytes:
        swp_pct = mem.swap_percent or 0.0
        click.echo(
            f"  Swap Usage       : {swp_pct:5.1f}% "
            f"({format_bytes(mem.swap_used_bytes or 0)} / {format_bytes(mem.swap_total_bytes)})"
        )
    click.echo()

    # 3. Disk Filesystem
    click.secho("[FILESYSTEM DISK USAGE]", fg="green", bold=True)
    for disk in snapshot.disks:
        click.echo(
            f"  Mount: {disk.mount_point:10s} "
            f"Usage: {disk.percent:5.1f}% "
            f"({format_bytes(disk.used_bytes)} / {format_bytes(disk.total_bytes)}) "
            f"Free: {format_bytes(disk.free_bytes)}"
        )
    click.echo()

    # 4. Monitored Services
    click.secho("[SYSTEMD SERVICES]", fg="green", bold=True)
    if snapshot.services:
        for svc in snapshot.services:
            svc_color = "green" if svc.is_active else "yellow"
            status_text = f"ACTIVE ({svc.sub_state})" if svc.is_active else f"INACTIVE ({svc.active_state}/{svc.sub_state})"
            click.secho(f"  [{status_text:24s}] ", fg=svc_color, nl=False)
            enabled_str = "enabled" if svc.is_enabled else ("disabled" if svc.is_enabled is False else "unknown")
            click.echo(f"{svc.service_name} (startup: {enabled_str})")
    else:
        click.echo("  No systemd services inspected.")
    click.echo()

    # 5. Supervised Target Processes
    click.secho("[SUPERVISED PROCESSES]", fg="green", bold=True)
    if snapshot.processes:
        header = f"  {'PID':>7s}  {'TARGET / NAME':25s}  {'STATE':10s}  {'CPU %':>6s}  {'RSS':>10s}  {'THREADS':>7s}  {'FDS':>5s}"
        click.echo(header)
        click.echo("  " + "-" * 76)
        for p in snapshot.processes:
            label = f"{p.target_id or ''} ({p.name})" if p.target_id else p.name
            click.echo(
                f"  {p.pid:7d}  {label[:25]:25s}  {p.state.value:10s}  "
                f"{p.cpu_percent:6.1f}  {format_bytes(p.rss_bytes):>10s}  "
                f"{p.num_threads or 0:7d}  {p.num_fds or 0:5d}"
            )
    else:
        configured_targets = [t.target_id for t in targets]
        click.echo(f"  No active processes found matching supervised targets: {configured_targets}")
    click.echo("================================================================================")


def _render_fault_status(status: Any, action_label: str, json_output: bool) -> None:
    """Format and display a FaultStatus response."""
    if json_output:
        import json
        click.echo(status.model_dump_json(indent=2))
        return

    status_color = "green" if status.is_running else "yellow"
    state_str = "RUNNING" if status.is_running else "STOPPED"
    if status.metrics.get("crashed"):
        status_color = "red"
        state_str = "CRASHED"

    click.echo("--------------------------------------------------------------------------------")
    click.secho(f"[{action_label.upper()}] Fault: {status.fault_name.upper()} | Target: {status.target_id}", fg="cyan", bold=True)
    click.secho(f"  State    : {state_str}", fg=status_color, bold=True)
    click.echo(f"  PID      : {status.pid or 'None'}")
    if status.metrics:
        click.echo("  Metrics  :")
        for k, v in status.metrics.items():
            click.echo(f"    - {k}: {v}")
    click.echo(f"  Details  : {status.details}")
    click.echo("--------------------------------------------------------------------------------")


@cli.group("fault")
def fault_group() -> None:
    """Controlled fault-injection subsystem for isolated research demo targets."""
    pass


@fault_group.command("cpu")
@click.argument("action", type=click.Choice(["start", "stop", "status", "cleanup"], case_sensitive=False), default="status")
@click.option("--json", "json_output", is_flag=True, help="Output status as JSON.")
def fault_cpu_cmd(action: str, json_output: bool) -> None:
    """Manage isolated CPU runaway fault demo (start, stop, status, cleanup)."""
    from self_healing.fault_injection.manager import FaultManager

    mgr = FaultManager()
    action = action.lower()
    if action == "start":
        res = mgr.start_fault("cpu")
        _render_fault_status(res, "START", json_output)
    elif action == "stop":
        res = mgr.stop_fault("cpu")
        _render_fault_status(res, "STOP", json_output)
    elif action == "cleanup":
        ok = mgr.cleanup_fault("cpu")
        if json_output:
            import json
            click.echo(json.dumps({"fault": "cpu", "cleanup": ok}))
        else:
            click.secho(f"CPU runaway demo target cleaned up successfully: {ok}", fg="green")
    else:
        res = mgr.status_fault("cpu")
        _render_fault_status(res, "STATUS", json_output)


@fault_group.command("memory")
@click.argument("action", type=click.Choice(["start", "stop", "status", "cleanup"], case_sensitive=False), default="status")
@click.option("--max-mb", type=int, default=256, help="Maximum memory ceiling in MB (hard safety cap: 512MB).")
@click.option("--chunk-mb", type=int, default=20, help="Allocation chunk size in MB.")
@click.option("--json", "json_output", is_flag=True, help="Output status as JSON.")
def fault_memory_cmd(action: str, max_mb: int, chunk_mb: int, json_output: bool) -> None:
    """Manage isolated memory growth fault demo (start, stop, status, cleanup)."""
    from self_healing.fault_injection.manager import FaultManager

    mgr = FaultManager()
    action = action.lower()
    if action == "start":
        res = mgr.start_fault("memory", max_mb=max_mb, chunk_mb=chunk_mb)
        _render_fault_status(res, "START", json_output)
    elif action == "stop":
        res = mgr.stop_fault("memory")
        _render_fault_status(res, "STOP", json_output)
    elif action == "cleanup":
        ok = mgr.cleanup_fault("memory")
        if json_output:
            import json
            click.echo(json.dumps({"fault": "memory", "cleanup": ok}))
        else:
            click.secho(f"Memory growth demo target cleaned up successfully: {ok}", fg="green")
    else:
        res = mgr.status_fault("memory")
        _render_fault_status(res, "STATUS", json_output)


@fault_group.command("service")
@click.argument("action", type=click.Choice(["start", "stop", "status", "cleanup"], case_sensitive=False), default="status")
@click.option("--auto-crash/--no-auto-crash", default=True, help="Immediately trigger service crash after startup.")
@click.option("--json", "json_output", is_flag=True, help="Output status as JSON.")
def fault_service_cmd(action: str, auto_crash: bool, json_output: bool) -> None:
    """Manage isolated service crash fault demo (start, stop, status, cleanup)."""
    from self_healing.fault_injection.manager import FaultManager

    mgr = FaultManager()
    action = action.lower()
    if action == "start":
        res = mgr.start_fault("service", auto_crash=auto_crash)
        _render_fault_status(res, "START", json_output)
    elif action == "stop":
        res = mgr.stop_fault("service")
        _render_fault_status(res, "STOP", json_output)
    elif action == "cleanup":
        ok = mgr.cleanup_fault("service")
        if json_output:
            import json
            click.echo(json.dumps({"fault": "service", "cleanup": ok}))
        else:
            click.secho(f"Service crash demo target cleaned up successfully: {ok}", fg="green")
    else:
        res = mgr.status_fault("service")
        _render_fault_status(res, "STATUS", json_output)


@fault_group.command("disk")
@click.argument("action", type=click.Choice(["start", "stop", "status", "cleanup"], case_sensitive=False), default="status")
@click.option("--max-mb", type=int, default=50, help="Maximum disk write cap in MB (hard safety cap: 100MB).")
@click.option("--json", "json_output", is_flag=True, help="Output status as JSON.")
def fault_disk_cmd(action: str, max_mb: int, json_output: bool) -> None:
    """Manage isolated disk/log growth fault demo (start, stop, status, cleanup)."""
    from self_healing.fault_injection.manager import FaultManager

    mgr = FaultManager()
    action = action.lower()
    if action == "start":
        res = mgr.start_fault("disk", max_mb=max_mb)
        _render_fault_status(res, "START", json_output)
    elif action == "stop":
        res = mgr.stop_fault("disk")
        _render_fault_status(res, "STOP", json_output)
    elif action == "cleanup":
        ok = mgr.cleanup_fault("disk")
        if json_output:
            import json
            click.echo(json.dumps({"fault": "disk", "cleanup": ok}))
        else:
            click.secho(f"Disk growth demo target cleaned up successfully: {ok}", fg="green")
    else:
        res = mgr.status_fault("disk")
        _render_fault_status(res, "STATUS", json_output)


@fault_group.command("deadlock")
@click.argument("action", type=click.Choice(["start", "stop", "status", "cleanup"], case_sensitive=False), default="status")
@click.option("--json", "json_output", is_flag=True, help="Output status as JSON.")
def fault_deadlock_cmd(action: str, json_output: bool) -> None:
    """Manage isolated deadlock fault demo (start, stop, status, cleanup)."""
    from self_healing.fault_injection.manager import FaultManager

    mgr = FaultManager()
    action = action.lower()
    if action == "start":
        res = mgr.start_fault("deadlock")
        _render_fault_status(res, "START", json_output)
    elif action == "stop":
        res = mgr.stop_fault("deadlock")
        _render_fault_status(res, "STOP", json_output)
    elif action == "cleanup":
        ok = mgr.cleanup_fault("deadlock")
        if json_output:
            import json
            click.echo(json.dumps({"fault": "deadlock", "cleanup": ok}))
        else:
            click.secho(f"Deadlock demo target cleaned up successfully: {ok}", fg="green")
    else:
        res = mgr.status_fault("deadlock")
        _render_fault_status(res, "STATUS", json_output)


@fault_group.command("status")
@click.option("--json", "json_output", is_flag=True, help="Output all fault statuses as JSON.")
def fault_status_all_cmd(json_output: bool) -> None:
    """Display overall status across all demo fault injectors."""
    from self_healing.fault_injection.manager import FaultManager

    mgr = FaultManager()
    statuses = mgr.status_all()

    if json_output:
        import json
        click.echo(json.dumps([s.model_dump() for s in statuses], indent=2))
        return

    click.echo("================================================================================")
    click.secho("  DEMO FAULT INJECTION SUBSYSTEM STATUS", fg="cyan", bold=True)
    click.echo("================================================================================")
    header = f"  {'FAULT':10s}  {'TARGET':15s}  {'STATE':10s}  {'PID':>7s}  {'DETAILS':30s}"
    click.echo(header)
    click.echo("  " + "-" * 76)
    for s in statuses:
        color = "green" if s.is_running else "yellow"
        state_label = "RUNNING" if s.is_running else "STOPPED"
        if s.metrics.get("crashed"):
            color = "red"
            state_label = "CRASHED"
        click.secho(f"  {s.fault_name:10s}  {s.target_id:15s}  {state_label:10s}  ", fg=color, nl=False)
        pid_str = str(s.pid) if s.pid else "-"
        click.echo(f"{pid_str:>7s}  {s.details[:30]:30s}")
    click.echo("================================================================================")


@fault_group.command("cleanup")
@click.option("--json", "json_output", is_flag=True, help="Output cleanup results as JSON.")
def fault_cleanup_all_cmd(json_output: bool) -> None:
    """Clean up and reset all demo fault targets and artifacts."""
    from self_healing.fault_injection.manager import FaultManager

    mgr = FaultManager()
    results = mgr.cleanup_all()

    if json_output:
        import json
        click.echo(json.dumps(results, indent=2))
        return

    click.echo("================================================================================")
    click.secho("  DEMO FAULT CLEANUP REPORT", fg="cyan", bold=True)
    click.echo("================================================================================")
    for name, ok in results.items():
        color = "green" if ok else "red"
        status_str = "CLEANED" if ok else "FAILED"
        click.secho(f"  [{status_str:7s}] Demo target for fault '{name}'", fg=color)
    click.echo("================================================================================")


@cli.command("verify")
@click.argument("target_id")
@click.option("--json", "json_output", is_flag=True, help="Output verification result as JSON.")
def verify_cmd(target_id: str, json_output: bool) -> None:
    """Run measurable post-recovery verification probes on an approved demo target."""
    from self_healing.config.settings import load_config
    from self_healing.targets.registry import TargetRegistry
    from self_healing.verification.engine import VerificationEngine

    cfg = load_config()
    registry = TargetRegistry(cfg.targets)
    try:
        target = registry.get(target_id)
    except Exception as ex:
        click.secho(f"Target lookup error: {ex}", fg="red")
        sys.exit(1)

    engine = VerificationEngine()
    result = engine.verify(target=target, incident_id="cli-manual-verify")

    if json_output:
        import json
        click.echo(json.dumps(result.model_dump(mode="json"), indent=2))
        return

    click.echo("================================================================================")
    status_color = "green" if result.verified else "red"
    click.secho(f"  POST-RECOVERY VERIFICATION: {result.status.value}", fg=status_color, bold=True)
    click.echo("================================================================================")
    click.echo(f"  Target ID:       {result.target_id}")
    click.echo(f"  Verified:        {result.verified}")
    click.echo(f"  Failed:          {result.failed}")
    click.echo(f"  Duration:        {result.verification_duration:.4f}s")
    click.echo(f"  Passed Checks:   {', '.join(result.checks_passed) if result.checks_passed else 'None'}")
    click.echo(f"  Failed Checks:   {', '.join(result.checks_failed) if result.checks_failed else 'None'}")
    click.echo(f"  Details:         {result.details}")
    if result.evidence:
        click.echo("  Evidence:")
        for k, v in result.evidence.items():
            click.echo(f"    - {k}: {v}")
    click.echo("================================================================================")
    if not result.verified:
        sys.exit(1)


def main() -> None:
    """Application CLI entry point."""
    cli()


if __name__ == "__main__":
    main()

