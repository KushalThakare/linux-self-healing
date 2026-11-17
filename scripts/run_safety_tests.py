#!/usr/bin/env python3
"""CLI Runner for Phase 15 — Robustness and Safety Testing.

Attempts to break the self-healing system safely across 15 failure vectors:
1. repeated CPU faults
2. repeated memory faults
3. service repeatedly crashing
4. recovery action failure
5. verification failure
6. invalid recovery target
7. unauthorized process target
8. excessive retry requests
9. duplicate detection events
10. malformed detection events
11. database failure
12. monitoring failure
13. detector failure
14. permission failure
15. recovery timeout

And verifies the 6 core safety invariants:
- arbitrary commands cannot execute
- unauthorized targets cannot be healed
- retry loops are prevented
- failures are recorded
- verification catches unsuccessful recovery
- the system fails safely

Generates structured JSON results at evaluation/results/robustness_safety_results.json
and prints an ASCII summary report.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Dict, List

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))


TEST_VECTORS = [
    {
        "id": "VECTOR-01",
        "name": "repeated_cpu_faults",
        "test_name": "tests/test_robustness_safety.py::test_vector_01_repeated_cpu_faults_flapping_and_cooldown",
        "description": "Rapid repeated CPU faults trigger flapping lockout and cooldown",
        "invariant": "Flapping lockout & cooldown rate limiter prevent thrashing",
    },
    {
        "id": "VECTOR-02",
        "name": "repeated_memory_faults",
        "test_name": "tests/test_robustness_safety.py::test_vector_02_repeated_memory_faults_rate_limiting",
        "description": "Repeated memory leak injections enforce cooldown rate limit",
        "invariant": "Guardrails block repeated actions during active cooldown",
    },
    {
        "id": "VECTOR-03",
        "name": "service_repeatedly_crashing",
        "test_name": "tests/test_robustness_safety.py::test_vector_03_service_repeatedly_crashing_escalation",
        "description": "Service repeatedly crashing exhausts retries and escalates",
        "invariant": "Automated retry limit halts loop and marks incident ESCALATED",
    },
    {
        "id": "VECTOR-04",
        "name": "recovery_action_failure",
        "test_name": "tests/test_robustness_safety.py::test_vector_04_recovery_action_failure_handled",
        "description": "Recovery action execution failure captured with structured error",
        "invariant": "Handler exception produces RecoveryResult(success=False) without crash",
    },
    {
        "id": "VECTOR-05",
        "name": "verification_failure",
        "test_name": "tests/test_robustness_safety.py::test_vector_05_verification_catches_unsuccessful_recovery",
        "description": "Verification probe detects persistent fault after remediation",
        "invariant": "Verification failure updates RecoveryResult and flags incident",
    },
    {
        "id": "VECTOR-06",
        "name": "invalid_recovery_target",
        "test_name": "tests/test_robustness_safety.py::test_vector_06_invalid_recovery_target_rejection",
        "description": "Bogus or unregistered target IDs rejected before execution",
        "invariant": "TargetRegistry & Guardrails reject unauthorized target IDs",
    },
    {
        "id": "VECTOR-07",
        "name": "unauthorized_process_target",
        "test_name": "tests/test_robustness_safety.py::test_vector_07_unauthorized_process_target_shield",
        "description": "Attempts to target PID 1, root daemons, or system paths blocked",
        "invariant": "PID boundary & identity safety raise SecurityViolationError",
    },
    {
        "id": "VECTOR-08",
        "name": "excessive_retry_requests",
        "test_name": "tests/test_robustness_safety.py::test_vector_08_excessive_retry_requests_blocked",
        "description": "Interventions with retry_count >= max_retries rejected",
        "invariant": "Hard ceiling on retries enforces incident escalation",
    },
    {
        "id": "VECTOR-09",
        "name": "duplicate_detection_events",
        "test_name": "tests/test_robustness_safety.py::test_vector_09_duplicate_detection_events_deduplication",
        "description": "Rapid duplicate detection events for active fault suppressed",
        "invariant": "Active fault tracker deduplicates alert storms",
    },
    {
        "id": "VECTOR-10",
        "name": "malformed_detection_events",
        "test_name": "tests/test_robustness_safety.py::test_vector_10_malformed_detection_events_handled_safely",
        "description": "Corrupted, null, or invalid detection events discarded safely",
        "invariant": "Defensive input parsing isolates malformed payloads",
    },
    {
        "id": "VECTOR-11",
        "name": "database_failure",
        "test_name": "tests/test_robustness_safety.py::test_vector_11_database_failure_graceful_degradation",
        "description": "SQLite database lock or disk full degrades gracefully",
        "invariant": "Storage exceptions isolated; orchestrator continues loop",
    },
    {
        "id": "VECTOR-12",
        "name": "monitoring_failure",
        "test_name": "tests/test_robustness_safety.py::test_vector_12_monitoring_failure_graceful_fallback",
        "description": "Telemetry collection /proc read error or psutil access denial",
        "invariant": "Collector falls back to boot time / safe system baselines",
    },
    {
        "id": "VECTOR-13",
        "name": "detector_failure",
        "test_name": "tests/test_robustness_safety.py::test_vector_13_detector_failure_isolation",
        "description": "Unhandled detector exception isolated without halting pipeline",
        "invariant": "Faulty detection rule isolated; healthy rules continue",
    },
    {
        "id": "VECTOR-14",
        "name": "permission_failure",
        "test_name": "tests/test_robustness_safety.py::test_vector_14_permission_failure_handling",
        "description": "EPERM / PermissionError on signaling handled cleanly",
        "invariant": "Permission denial caught and structured failure recorded",
    },
    {
        "id": "VECTOR-15",
        "name": "recovery_timeout",
        "test_name": "tests/test_robustness_safety.py::test_vector_15_recovery_timeout_enforcement",
        "description": "Slow or hanging recovery action cleanly terminated at timeout",
        "invariant": "Execution bounded by timeout; aborts hung tasks cleanly",
    },
]

SAFETY_PROPERTIES = [
    {
        "id": "PROPERTY-01",
        "name": "arbitrary_commands_cannot_execute",
        "test_name": "tests/test_robustness_safety.py::test_safety_property_arbitrary_commands_cannot_execute",
        "description": "Raw strings and shell command injection attempts rejected",
        "invariant": "Zero arbitrary shell execution; typed allowlist mandatory",
    },
    {
        "id": "PROPERTY-02",
        "name": "unauthorized_targets_cannot_be_healed",
        "test_name": "tests/test_robustness_safety.py::test_safety_property_unauthorized_targets_cannot_be_healed",
        "description": "Host and unapproved targets shielded from modifications",
        "invariant": "Restricted strictly to registered, enabled demo targets",
    },
    {
        "id": "PROPERTY-03",
        "name": "retry_loops_are_prevented",
        "test_name": "tests/test_robustness_safety.py::test_safety_property_retry_loops_are_prevented",
        "description": "Ceilings on retries, cooldowns, and flapping prevent loops",
        "invariant": "Deterministic escalation terminates retry cycles",
    },
    {
        "id": "PROPERTY-04",
        "name": "failures_are_recorded",
        "test_name": "tests/test_robustness_safety.py::test_safety_property_failures_are_recorded",
        "description": "All policy rejections and recovery failures produce audit records",
        "invariant": "Incident store records immutable failure history",
    },
    {
        "id": "PROPERTY-05",
        "name": "verification_catches_unsuccessful_recovery",
        "test_name": "tests/test_robustness_safety.py::test_safety_property_verification_catches_unsuccessful_recovery",
        "description": "Unresolved faults flagged as unsuccessful despite OS-level return",
        "invariant": "Verification outcome overrides candidate success flag",
    },
    {
        "id": "PROPERTY-06",
        "name": "system_fails_safely",
        "test_name": "tests/test_robustness_safety.py::test_safety_property_system_fails_safely",
        "description": "Cascading failures do not crash the orchestrator or host VM",
        "invariant": "End-to-end exception containment guarantees uptime",
    },
]


def run_single_test(test_target: str) -> Dict[str, Any]:
    """Execute a single test using pytest and measure execution latency."""
    cmd = [
        str(PROJECT_ROOT / ".venv" / "bin" / "pytest"),
        test_target,
        "-q",
        "--tb=short",
    ]
    t0 = time.perf_counter()
    res = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    passed = res.returncode == 0
    return {
        "passed": passed,
        "latency_ms": round(latency_ms, 2),
        "returncode": res.returncode,
        "stdout": res.stdout.strip(),
        "stderr": res.stderr.strip(),
    }


def main() -> int:
    print("=" * 80)
    print("PHASE 15 — ROBUSTNESS AND SAFETY TESTING SUITE")
    print("Attempting to break the self-healing system safely across 15 failure vectors")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 80)

    vector_results = []
    property_results = []
    all_passed = True

    print("\n--- [PART 1: 15 ROBUSTNESS FAILURE VECTORS] ---")
    print(f"{'ID':<11} | {'Vector Name':<32} | {'Status':<8} | {'Latency':<9} | {'Invariant Verified'}")
    print("-" * 105)

    for v in TEST_VECTORS:
        out = run_single_test(v["test_name"])
        status = "PASSED" if out["passed"] else "FAILED"
        if not out["passed"]:
            all_passed = False
        print(f"{v['id']:<11} | {v['name']:<32} | {status:<8} | {out['latency_ms']:>6.1f}ms | {v['invariant']}")
        vector_results.append({
            **v,
            "status": status,
            "passed": out["passed"],
            "latency_ms": out["latency_ms"],
            "details": out["stdout"] if out["passed"] else out["stderr"],
        })

    print("\n--- [PART 2: 6 CORE SAFETY PROPERTY INVARIANTS] ---")
    print(f"{'ID':<13} | {'Property Invariant':<35} | {'Status':<8} | {'Latency':<9} | {'Defense Description'}")
    print("-" * 110)

    for p in SAFETY_PROPERTIES:
        out = run_single_test(p["test_name"])
        status = "PASSED" if out["passed"] else "FAILED"
        if not out["passed"]:
            all_passed = False
        print(f"{p['id']:<13} | {p['name']:<35} | {status:<8} | {out['latency_ms']:>6.1f}ms | {p['description']}")
        property_results.append({
            **p,
            "status": status,
            "passed": out["passed"],
            "latency_ms": out["latency_ms"],
            "details": out["stdout"] if out["passed"] else out["stderr"],
        })

    # Summary calculations
    total_tests = len(vector_results) + len(property_results)
    passed_tests = sum(1 for r in vector_results if r["passed"]) + sum(1 for r in property_results if r["passed"])
    pass_rate = (passed_tests / total_tests) * 100.0

    print("\n" + "=" * 80)
    print("ROBUSTNESS & SAFETY VERIFICATION SUMMARY")
    print(f"Total Vectors Tested:     {len(vector_results)}/15 PASSED ({sum(1 for r in vector_results if r['passed'])} passed)")
    print(f"Safety Invariants Tested: {len(property_results)}/6 PASSED ({sum(1 for r in property_results if r['passed'])} passed)")
    print(f"Overall Pass Rate:        {pass_rate:.1f}% ({passed_tests}/{total_tests})")
    print(f"Safe Failure Enforced:    {'YES - 100% BLOCKED & ISOLATED' if all_passed else 'NO - FAILURES DETECTED'}")
    print("=" * 80)

    # Persist structured JSON results
    output_dir = PROJECT_ROOT / "evaluation" / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "robustness_safety_results.json"

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_tests": total_tests,
        "passed_tests": passed_tests,
        "pass_rate_percent": pass_rate,
        "all_passed": all_passed,
        "vectors_tested": len(vector_results),
        "safety_properties_tested": len(property_results),
        "failure_vectors": vector_results,
        "safety_properties": property_results,
    }

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"\n[+] Results persisted to: {summary_path}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
