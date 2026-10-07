"""Unit and integration tests for the Phase 7 Recovery Executor subsystem.

Verifies:
1. Hard security boundaries: strict rejection of arbitrary shell commands and unallowlisted actions.
2. Target validation: restriction to approved demo targets and protection of system processes.
3. Guardrail token validation via execute_guardrail_approved.
4. Dry-run execution across all 5 allowlisted actions.
5. Real execution and verification of OS-level changes on isolated demo targets.
6. Path traversal and workspace boundary defense in log cleanup.
"""

import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Generator
import psutil
import pytest

from self_healing.core.exceptions import (
    ActionExecutionError,
    SecurityViolationError,
    TargetNotFoundError,
)
from self_healing.core.models import (
    AllowedActionType,
    GuardrailDecision,
    GuardrailStatus,
    RecoveryAction,
    RecoveryResult,
    RiskLevel,
    TargetSpec,
)
from self_healing.guardrails.engine import SafetyGuardrailEngine
from self_healing.guardrails.registry import AllowedActionRegistry
from self_healing.recovery.executor import RecoveryExecutor
from self_healing.targets.registry import TargetRegistry


@pytest.fixture
def workspace_dir() -> Path:
    return Path(__file__).parent.parent.resolve()


@pytest.fixture
def test_target_registry(workspace_dir: Path) -> TargetRegistry:
    """Preconfigured TargetRegistry with approved isolated demo targets."""
    reg = TargetRegistry()
    targets = [
        TargetSpec(
            target_id="demo-cpu",
            process_name="python3",
            cmdline_substring="cpu_spin",
            working_dir_prefix=str(workspace_dir),
        ),
        TargetSpec(
            target_id="demo-memory",
            process_name="python3",
            cmdline_substring="memory_leak",
            working_dir_prefix=str(workspace_dir),
        ),
        TargetSpec(
            target_id="demo-service",
            process_name="python3",
            cmdline_substring="service_worker",
            expected_port=8095,
            working_dir_prefix=str(workspace_dir),
        ),
        TargetSpec(
            target_id="demo-disk",
            process_name="python3",
            cmdline_substring="disk_write",
            working_dir_prefix=str(workspace_dir),
        ),
        TargetSpec(
            target_id="demo-deadlock",
            process_name="python3",
            cmdline_substring="deadlock_hang",
            working_dir_prefix=str(workspace_dir),
        ),
    ]
    for t in targets:
        reg.register(t)
    return reg


@pytest.fixture
def executor(test_target_registry: TargetRegistry) -> RecoveryExecutor:
    return RecoveryExecutor(target_registry=test_target_registry, dry_run=False)


# -------------------------------------------------------------------------
# 1. Security & Pre-Execution Validation Tests
# -------------------------------------------------------------------------
def test_reject_arbitrary_shell_command_string(executor: RecoveryExecutor):
    """Hard invariant: RecoveryExecutor must NEVER accept arbitrary shell strings."""
    with pytest.raises(SecurityViolationError, match="only accepts validated RecoveryAction"):
        executor.execute("rm -rf /")

    with pytest.raises(SecurityViolationError, match="only accepts validated RecoveryAction"):
        executor.execute("kill -9 1")

    with pytest.raises(SecurityViolationError, match="only accepts validated RecoveryAction"):
        executor.execute({"cmd": "bash -c 'echo hacked'"})


def test_reject_unapproved_target_id(executor: RecoveryExecutor):
    """RecoveryExecutor must reject targets not registered in TargetRegistry."""
    action = RecoveryAction(
        action_id="act-unapproved-1",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target="unknown-daemon",
        reason="Test unapproved target",
    )
    with pytest.raises(TargetNotFoundError, match="not an approved demo target"):
        executor.execute(action)


def test_reject_protected_system_entities(executor: RecoveryExecutor):
    """RecoveryExecutor must block actions attempting to target protected system processes."""
    # Attempting to craft a target spec targeting init or sshd
    protected_spec = TargetSpec(
        target_id="fake-sshd",
        process_name="sshd",
        cmdline_substring="/usr/sbin/sshd",
        working_dir_prefix="/tmp",
    )
    action = RecoveryAction(
        action_id="act-prot-1",
        action_type=AllowedActionType.TERMINATE_DEMO_PROCESS,
        target="fake-sshd",
        reason="Test protected process block",
    )
    with pytest.raises(SecurityViolationError, match="protected process"):
        executor.execute(action, target_spec=protected_spec)


def test_reject_target_incompatible_with_action(executor: RecoveryExecutor):
    """RecoveryExecutor must reject actions where target is outside action.allowed_targets."""
    action = RecoveryAction(
        action_id="act-incompat-1",
        action_type=AllowedActionType.CLEANUP_DEMO_LOGS,
        target="demo-cpu",
        reason="Invalid target for log cleanup",
        allowed_targets=["demo-disk"],
    )
    with pytest.raises(SecurityViolationError, match="not permitted for action"):
        executor.execute(action)


def test_reject_execution_without_guardrail_approval(executor: RecoveryExecutor):
    """execute_guardrail_approved must reject actions lacking GUARDRAIL APPROVED status."""
    action = AllowedActionRegistry.create_action(
        AllowedActionType.TERMINATE_DEMO_PROCESS,
        target="demo-cpu",
        reason="Test rejected decision",
    )
    rejected_decision = GuardrailDecision(
        decision_id="dec-rej-1",
        action_id=action.action_id,
        target_id="demo-cpu",
        action_type=action.action_type,
        action_params={},
        allowed=False,
        is_dry_run=False,
        status=GuardrailStatus.REJECTED,
        violations=["Check 4 Failed: target unapproved"],
        reasons=["Rejected"],
    )

    with pytest.raises(SecurityViolationError, match="does not possess a valid GUARDRAIL APPROVED decision"):
        executor.execute_guardrail_approved(rejected_decision, action)


def test_reject_mismatched_guardrail_decision_action_id(executor: RecoveryExecutor):
    """execute_guardrail_approved must reject decision when action_id does not match."""
    action = AllowedActionRegistry.create_action(
        AllowedActionType.TERMINATE_DEMO_PROCESS,
        target="demo-cpu",
        reason="Test mismatched id",
    )
    decision = GuardrailDecision(
        decision_id="dec-app-1",
        action_id="different-action-uuid",
        target_id="demo-cpu",
        action_type=action.action_type,
        action_params={},
        allowed=True,
        is_dry_run=False,
        status=GuardrailStatus.APPROVED,
        violations=[],
        reasons=["Approved"],
    )

    with pytest.raises(SecurityViolationError, match="does not match candidate action_id"):
        executor.execute_guardrail_approved(decision, action)


# -------------------------------------------------------------------------
# 2. Dry-Run Execution Tests
# -------------------------------------------------------------------------
def test_dry_run_all_five_actions(executor: RecoveryExecutor, workspace_dir: Path):
    """Verify that all 5 allowlisted actions simulate cleanly in dry-run mode."""
    actions = [
        AllowedActionRegistry.create_action(
            AllowedActionType.TERMINATE_DEMO_PROCESS,
            target="demo-cpu",
            reason="Simulated runaway CPU kill",
        ),
        AllowedActionRegistry.create_action(
            AllowedActionType.LOWER_DEMO_PROCESS_PRIORITY,
            target="demo-cpu",
            reason="Simulated renice",
        ),
        AllowedActionRegistry.create_action(
            AllowedActionType.CLEANUP_DEMO_LOGS,
            target="demo-disk",
            reason="Simulated log cleanup",
        ),
        AllowedActionRegistry.create_action(
            AllowedActionType.RESTART_DEMO_SERVICE,
            target="demo-service",
            reason="Simulated service restart",
        ),
        AllowedActionRegistry.create_action(
            AllowedActionType.RESTART_DEMO_APPLICATION,
            target="demo-memory",
            reason="Simulated app restart",
        ),
    ]

    for act in actions:
        res = executor.execute(act, dry_run=True)
        assert res.success is True
        assert res.dry_run is True
        assert res.execution_latency_ms >= 0.0
        assert "[DRY-RUN]" in res.output_message
        assert res.error is None
        assert res.details.get("simulated") is True


# -------------------------------------------------------------------------
# 3. Real Execution Tests on Isolated Demo Targets
# -------------------------------------------------------------------------
def test_real_execute_terminate_demo_process(executor: RecoveryExecutor, workspace_dir: Path):
    """Start an isolated demo CPU process, execute terminate_demo_process, verify exit."""
    # Spawn demo cpu_spin workload
    proc = subprocess.Popen(
        [sys.executable, "-m", "self_healing.targets.demo_workloads", "cpu_spin"],
        cwd=str(workspace_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.3)
    assert proc.poll() is None, "Demo process should be running"
    pid = proc.pid

    try:
        action = AllowedActionRegistry.create_action(
            AllowedActionType.TERMINATE_DEMO_PROCESS,
            target="demo-cpu",
            reason="Unit test terminating demo CPU worker",
            parameters={"pid": pid, "grace_period_seconds": 1.0},
        )

        res = executor.execute(action, dry_run=False)
        assert res.success is True
        assert res.dry_run is False
        assert pid in res.details["terminated_pids"]
        proc.poll()
        assert not psutil.pid_exists(pid) or proc.returncode is not None, f"PID {pid} should no longer be active"
    finally:
        if psutil.pid_exists(pid):
            os.kill(pid, signal.SIGKILL)


def test_real_execute_lower_demo_process_priority(executor: RecoveryExecutor, workspace_dir: Path):
    """Start an isolated demo process, execute lower_demo_process_priority, verify niceness increment."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "self_healing.targets.demo_workloads", "cpu_spin"],
        cwd=str(workspace_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.3)
    assert proc.poll() is None
    pid = proc.pid

    try:
        initial_nice = psutil.Process(pid).nice()
        action = AllowedActionRegistry.create_action(
            AllowedActionType.LOWER_DEMO_PROCESS_PRIORITY,
            target="demo-cpu",
            reason="Unit test renicing demo CPU worker",
            parameters={"pid": pid, "nice_increment": 8},
        )

        res = executor.execute(action, dry_run=False)
        assert res.success is True
        assert res.dry_run is False
        assert len(res.details["reniced_details"]) > 0

        updated_nice = psutil.Process(pid).nice()
        assert updated_nice == min(19, initial_nice + 8)
    finally:
        if psutil.pid_exists(pid):
            os.kill(pid, signal.SIGKILL)


def test_real_execute_cleanup_demo_logs(executor: RecoveryExecutor, workspace_dir: Path):
    """Create simulated logs inside workspace demo_scratch, execute cleanup, verify file removal."""
    log_dir = workspace_dir / "demo_scratch" / "test_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    test_log = log_dir / "test_disk_growth.log"
    test_log.write_text("A" * 1024 * 100)  # 100 KB
    assert test_log.exists()

    action = AllowedActionRegistry.create_action(
        AllowedActionType.CLEANUP_DEMO_LOGS,
        target="demo-disk",
        reason="Unit test cleanup logs",
        parameters={"directory": str(log_dir)},
    )

    res = executor.execute(action, dry_run=False)
    assert res.success is True
    assert res.dry_run is False
    assert res.details["reclaimed_bytes"] >= 1024 * 100
    assert "test_disk_growth.log" in res.details["files_removed"]
    assert not test_log.exists()


def test_cleanup_demo_logs_rejects_paths_outside_workspace(executor: RecoveryExecutor, workspace_dir: Path):
    """Enforce security boundary: paths outside workspace are strictly rejected."""
    action = AllowedActionRegistry.create_action(
        AllowedActionType.CLEANUP_DEMO_LOGS,
        target="demo-disk",
        reason="Directory traversal attack attempt",
        parameters={"directory": "/var/log"},
    )

    with pytest.raises(SecurityViolationError, match="outside authorized workspace"):
        executor.execute(action, dry_run=False)

    action_traversal = AllowedActionRegistry.create_action(
        AllowedActionType.CLEANUP_DEMO_LOGS,
        target="demo-disk",
        reason="Relative directory traversal attempt",
        parameters={"directory": str(workspace_dir / "../../etc")},
    )

    with pytest.raises(SecurityViolationError, match="outside authorized workspace"):
        executor.execute(action_traversal, dry_run=False)


def test_real_execute_restart_demo_service(executor: RecoveryExecutor, workspace_dir: Path):
    """Spawn demo HTTP service on test port, execute restart_demo_service, verify new PID."""
    test_port = 8098
    # Start initial service instance
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "self_healing.targets.demo_workloads",
            "service_worker",
            "--port",
            str(test_port),
        ],
        cwd=str(workspace_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.4)
    old_pid = proc.pid
    assert psutil.pid_exists(old_pid)

    new_pid = None
    try:
        custom_spec = TargetSpec(
            target_id="demo-service",
            process_name="python3",
            cmdline_substring="service_worker",
            expected_port=test_port,
            working_dir_prefix=str(workspace_dir),
        )

        action = AllowedActionRegistry.create_action(
            AllowedActionType.RESTART_DEMO_SERVICE,
            target="demo-service",
            reason="Unit test restart service",
            parameters={"pid": old_pid},
        )

        res = executor.execute(action, target_spec=custom_spec, dry_run=False)
        assert res.success is True
        assert res.dry_run is False
        assert old_pid in res.details["recycled_pids"]
        new_pid = res.details["new_pid"]
        assert new_pid != old_pid
        assert psutil.pid_exists(new_pid)
    finally:
        if psutil.pid_exists(old_pid):
            os.kill(old_pid, signal.SIGKILL)
        if new_pid and psutil.pid_exists(new_pid):
            os.kill(new_pid, signal.SIGKILL)


def test_real_execute_restart_demo_application(executor: RecoveryExecutor, workspace_dir: Path):
    """Spawn demo memory workload, execute restart_demo_application, verify process recycled."""
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "self_healing.targets.demo_workloads",
            "memory_leak",
            "--max-mb",
            "30",
        ],
        cwd=str(workspace_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.3)
    old_pid = proc.pid
    assert psutil.pid_exists(old_pid)

    new_pid = None
    try:
        action = AllowedActionRegistry.create_action(
            AllowedActionType.RESTART_DEMO_APPLICATION,
            target="demo-memory",
            reason="Unit test restart application",
            parameters={"pid": old_pid, "max_mb": 30},
        )

        res = executor.execute(action, dry_run=False)
        assert res.success is True
        assert res.dry_run is False
        assert old_pid in res.details["recycled_pids"]
        new_pid = res.details["new_pid"]
        assert new_pid != old_pid
        assert psutil.pid_exists(new_pid)
    finally:
        if psutil.pid_exists(old_pid):
            os.kill(old_pid, signal.SIGKILL)
        if new_pid and psutil.pid_exists(new_pid):
            os.kill(new_pid, signal.SIGKILL)


def test_guardrail_approved_end_to_end_flow(executor: RecoveryExecutor, test_target_registry: TargetRegistry):
    """End-to-end integration: GuardrailEngine approves action -> RecoveryExecutor executes."""
    guardrail = SafetyGuardrailEngine(target_registry=test_target_registry, dry_run=True)

    action = AllowedActionRegistry.create_action(
        AllowedActionType.TERMINATE_DEMO_PROCESS,
        target="demo-cpu",
        reason="End to end test",
        custom_evidence_keys=["average_cpu_percent"],
    )
    evidence = {"target_id": "demo-cpu", "average_cpu_percent": 95.5}

    decision = guardrail.evaluate(action, evidence=evidence, dry_run=True)
    assert decision.status == GuardrailStatus.APPROVED

    res = executor.execute_guardrail_approved(decision, action)
    assert res.success is True
    assert res.dry_run is True
    assert "[DRY-RUN]" in res.output_message
