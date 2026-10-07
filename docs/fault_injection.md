# Controlled Fault-Injection Subsystem

## 1. Overview and Design Philosophy

The **Controlled Fault-Injection Subsystem** is an isolated, safety-critical framework built for Linux self-healing research and automated chaos testing. In strict adherence to **Rules 1, 2, 4, 6, and 17** of `AGENTS.md`, this subsystem allows operators to induce and observe deterministic operating system anomalies without risking VM stability or interfering with production services.

### Core Safety Invariants
1. **Isolated Demo Targets Only**: Fault injectors strictly operate on approved, ephemeral demo targets registered in `config/targets.yaml`.
2. **Zero Blast Radius**: System daemons (e.g. `systemd`, `sshd`, `cron`), kernel processes, shells, and PIDs $\le 2$ are rejected with `SecurityViolationError`.
3. **Hard Resource Ceilings**:
   - **CPU**: Confined to 1 worker thread (leaves remaining cores 100% available).
   - **RAM**: Hard ceiling capped at 256 MB (hard safety limit $\le 512$ MB vs 11.25 GB VM total).
   - **Disk**: Hard ceiling capped at 50 MB (hard safety limit $\le 100$ MB vs 15.7 GB VM free space).
   - **Network**: Binds exclusively to localhost `127.0.0.1:8085`.
4. **Complete Reversibility**: Every fault provides `start`, `stop`, `status`, and `cleanup` operations to return the VM to pristine condition.

---

## 2. Architecture and Component Overview

```
+-----------------------------------------------------------------------------------+
|                        Operator & Research CLI                                    |
|   python -m self_healing fault {cpu|memory|service|disk|deadlock} {action}        |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------------+
|                           FaultManager Registry                                   |
|   (Validates TargetSpec, coordinates state tracking, enforces boundaries)          |
+-----------------------------------------------------------------------------------+
         |               |                 |                 |               |
         v               v                 v                 v               v
  +-------------+ +---------------+ +---------------+ +-------------+ +---------------+
  | CpuRunaway  | | MemoryGrowth  | | ServiceCrash  | | DiskGrowth  | |   Deadlock    |
  |  Injector   | |   Injector    | |   Injector    | |  Injector   | |   Injector    |
  +-------------+ +---------------+ +---------------+ +-------------+ +---------------+
         |               |                 |                 |               |
         | Spawns & tracks via TargetSpec allowlist & state files in .fault_state/   |
         v               v                 v                 v               v
+-----------------------------------------------------------------------------------+
|                            Isolated Demo Targets                                  |
|   src/self_healing/targets/demo_workloads.py (subprocess workers within repo)    |
|   - demo-cpu: 1-core arithmetic spin loop                                         |
|   - demo-memory: chunked bytearray allocation (capped at 256MB)                   |
|   - demo-service: lightweight HTTP worker on 127.0.0.1:8085                       |
|   - demo-disk: dummy log generation in demo_scratch/logs/ (capped at 50MB)        |
|   - demo-deadlock: AB-BA circular lock inversion thread deadlock                  |
+-----------------------------------------------------------------------------------+
```

### Module Responsibilities
- `src/self_healing/fault_injection/base.py`: Defines `BaseFaultInjector` abstract base class with PID tracking, state serialization (`.fault_state/{name}.json`), and blast-radius validation.
- `src/self_healing/targets/demo_workloads.py`: Standalone, self-contained worker routines executing inside the project workspace.
- `src/self_healing/fault_injection/cpu.py`: `CpuRunawayInjector`.
- `src/self_healing/fault_injection/memory.py`: `MemoryGrowthInjector`.
- `src/self_healing/fault_injection/service.py`: `ServiceCrashInjector`.
- `src/self_healing/fault_injection/disk.py`: `DiskGrowthInjector`.
- `src/self_healing/fault_injection/deadlock.py`: `DeadlockInjector`.
- `src/self_healing/fault_injection/manager.py`: `FaultManager` orchestrator providing unified query and batch cleanup.
- `src/self_healing/cli.py`: Click command group `fault` exposing operator commands.

---

## 3. Detailed Fault Mechanisms

### 3.1 CPU Runaway (`demo-cpu`)
- **Fault Type**: `FaultType.HIGH_CPU`
- **Target Specification**: Target ID `demo-cpu`, command substring `demo_workloads cpu_spin`.
- **Mechanism**: Spawns an isolated Python process that executes a tight arithmetic loop (`math.sqrt`) on a single thread.
- **Observed Behavior**:
  - The process consumes ~95–100% of one core.
  - Global system load average increases moderately, while other CPU cores remain idle.
- **Safety Ceiling**: Single thread only. Multi-threading is intentionally disabled to avoid CPU starvation.
- **Cleanup**: Sends `SIGTERM` to the tracked process, waits up to 3.0s, and escalates to `SIGKILL` if unresponsive.

### 3.2 Memory Growth (`demo-memory`)
- **Fault Type**: `FaultType.MEMORY_LEAK`
- **Target Specification**: Target ID `demo-memory`, command substring `demo_workloads memory_leak`.
- **Mechanism**: Incrementally allocates 20 MB `bytearray` chunks every 0.5 seconds and retains references in memory. Pages are faulted in immediately by writing non-zero bytes.
- **Observed Behavior**:
  - Monotonic growth of Resident Set Size (RSS) and Virtual Memory Size (VMS).
  - Memory usage plateaus once the ceiling is reached.
- **Safety Ceiling**: Default cap is 256 MB. A hard programmatic upper bound of 512 MB is enforced, preventing OS Out-Of-Memory (OOM) invocations.
- **Cleanup**: Sends `SIGTERM` to the process. The operating system kernel immediately reclaims all heap allocations.

### 3.3 Service Crash (`demo-service`)
- **Fault Type**: `FaultType.PROCESS_CRASH`
- **Target Specification**: Target ID `demo-service`, command substring `demo_workloads service_worker`, port `8085`.
- **Mechanism**: Spawns a lightweight Python HTTP server listening on `127.0.0.1:8085`. When injected with `--auto-crash` (default), triggers an unhandled termination via `GET /crash`, causing `os._exit(1)`.
- **Observed Behavior**:
  - Service transitions from active listening to dead.
  - Process exits abruptly with code 1.
  - TCP port `8085` closes and health probes fail.
- **Safety Ceiling**: Binds strictly to loopback interface (`127.0.0.1`), port `8085`. Does not touch systemd units or root ports.
- **Cleanup**: Verifies process termination, ensures port `8085` is released, and clears tracking state.

### 3.4 Disk / Log Growth (`demo-disk`)
- **Fault Type**: `FaultType.DISK_GROWTH`
- **Target Specification**: Target ID `demo-disk`, command substring `demo_workloads disk_write`.
- **Mechanism**: Rapidly writes 1 MB dummy log entries to `demo_scratch/logs/demo_disk_growth.log` within the repository workspace.
- **Observed Behavior**:
  - File size increases steadily by several megabytes per second.
  - Demonstrates rapid disk space consumption without impacting system loggers (`journald`).
- **Safety Ceiling**: Hard limit of 50 MB (maximum allowable configuration 100 MB). Directory paths are validated to ensure they reside exclusively within the repository workspace.
- **Cleanup**: Terminates the disk writer process and deletes `demo_scratch/logs/` completely using `shutil.rmtree`.

### 3.5 Deadlock (`demo-deadlock`)
- **Fault Type**: `FaultType.DEADLOCK`
- **Target Specification**: Target ID `demo-deadlock`, command substring `demo_workloads deadlock_hang`.
- **Mechanism**: Runs two worker threads that acquire two locks in reverse order:
  - Thread 1: Acquires `Lock A` $\rightarrow$ attempts `Lock B`.
  - Thread 2: Acquires `Lock B` $\rightarrow$ attempts `Lock A`.
- **Observed Behavior**:
  - The process enters permanent user-space lock contention.
  - Process state transitions to `SLEEPING` / hung.
  - CPU utilization drops to 0.0% while the process remains present in the process table.
- **Safety Ceiling**: Fully self-contained in user space. Zero CPU overhead, zero disk I/O, zero network traffic.
- **Cleanup**: Sends `SIGTERM` to the deadlocked process and clears state.

---

## 4. CLI Command Reference

All injectors support four standardized lifecycle actions: `start`, `stop`, `status`, and `cleanup`.

### 4.1 CPU Runaway
```bash
# Start CPU runaway demo
python -m self_healing fault cpu start

# Inspect CPU utilization and process state
python -m self_healing fault cpu status

# Stop CPU runaway process
python -m self_healing fault cpu stop

# Cleanup demo target and reset state
python -m self_healing fault cpu cleanup
```

### 4.2 Memory Growth
```bash
# Start memory growth demo (default cap: 256MB)
python -m self_healing fault memory start --max-mb 256 --chunk-mb 20

# Query memory RSS and growth metrics
python -m self_healing fault memory status

# Stop memory growth demo
python -m self_healing fault memory stop

# Cleanup demo target and release RAM
python -m self_healing fault memory cleanup
```

### 4.3 Service Crash
```bash
# Start and immediately crash demo HTTP service
python -m self_healing fault service start

# Check service status (reports crashed exit code)
python -m self_healing fault service status

# Ensure service is stopped
python -m self_healing fault service stop

# Cleanup service target
python -m self_healing fault service cleanup
```

### 4.4 Disk / Log Growth
```bash
# Start rapid log growth demo (default cap: 50MB)
python -m self_healing fault disk start --max-mb 50

# Query log directory size and written MB
python -m self_healing fault disk status

# Stop disk writer
python -m self_healing fault disk stop

# Cleanup and purge generated log files
python -m self_healing fault disk cleanup
```

### 4.5 Deadlock
```bash
# Start deadlocked worker threads
python -m self_healing fault deadlock start

# Inspect deadlocked process (verifies SLEEPING / hung state)
python -m self_healing fault deadlock status

# Terminate deadlocked process
python -m self_healing fault deadlock stop

# Cleanup deadlock target
python -m self_healing fault deadlock cleanup
```

### 4.6 Subsystem Overview & Global Cleanup
```bash
# View live status table for all 5 demo targets
python -m self_healing fault status

# Output all statuses in normalized JSON
python -m self_healing fault status --json

# Run comprehensive cleanup sweep across all demo targets
python -m self_healing fault cleanup
```

---

## 5. Verification and Acceptance Procedures

To confirm system integrity before and after testing:
1. **Health Verification**:
   ```bash
   python -m self_healing health
   ```
2. **Subsystem Reset**:
   ```bash
   python -m self_healing fault cleanup
   ```
3. **Automated Unit & Integration Test Suite**:
   ```bash
   pytest tests/test_fault_injection.py -v
   ```
