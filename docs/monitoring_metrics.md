# Linux Self-Healing Framework: Monitoring Subsystem & Telemetry Catalog

## 1. Subsystem Architecture Overview

The monitoring subsystem provides non-intrusive, strictly **read-only** observability into the host Linux operating environment and supervised target processes. It fulfills the first stage in the core closed-loop lifecycle:

$$\mathbf{MONITOR} \longrightarrow \text{DETECT} \longrightarrow \text{DIAGNOSE} \longrightarrow \text{GUARDRAIL} \longrightarrow \text{HEAL} \longrightarrow \text{VERIFY}$$

### Core Design Principles
1. **Strictly Read-Only**: The monitoring subsystem contains zero mutating commands, zero signal delivery, and zero service management operations.
2. **Hybrid Kernel Observability**: Leverages `psutil` for cross-version portable metrics, complemented by direct parsing of the Linux `/proc` virtual filesystem for low-overhead, high-fidelity OS internals.
3. **Restricted Service Queries**: Uses `systemctl` strictly for read-only unit inspection (`show` and `is-active`), validating service names against an allowlist regex to eliminate injection risks.
4. **Strict Safe-PID Isolation**: Rejects any attempts to target PID 0, PID 1 (`systemd`), PID 2 (`kthreadd`), or framework internal processes.

---

## 2. Telemetry Metrics Catalog & Exact Sources

The internal monitoring model normalizes telemetry into typed Pydantic structures (`SystemSnapshot`, `MetricSnapshot`, `SystemCpuMetrics`, `SystemMemoryMetrics`, `DiskUsageMetrics`, `ProcessMetrics`, `ServiceMetrics`).

### 2.1 System Uptime & Scheduler Metrics

| Metric Field | Model | Normalized Unit | Exact Data Source | Linux Kernel Interface / API | Description |
|---|---|---|---|---|---|
| `uptime_seconds` | `SystemSnapshot` | Seconds (`float`) | `/proc/uptime` | Line 1, field 1 | Time elapsed since Linux system boot. |
| `idle_seconds` | `SystemSnapshot` | Seconds (`float`) | `/proc/uptime` | Line 1, field 2 | Cumulative time spent by cores in the idle task. |
| `load_1m` | `SystemCpuMetrics` | Load count (`float`) | `/proc/loadavg` | Field 1 | Average number of runnable or uninterruptible tasks over 1 minute. |
| `load_5m` | `SystemCpuMetrics` | Load count (`float`) | `/proc/loadavg` | Field 2 | Average number of runnable or uninterruptible tasks over 5 minutes. |
| `load_15m` | `SystemCpuMetrics` | Load count (`float`) | `/proc/loadavg` | Field 3 | Average number of runnable or uninterruptible tasks over 15 minutes. |
| `context_switches` | `SystemCpuMetrics` | Counter (`int`) | `/proc/stat` | `ctxt <count>` | Cumulative count of CPU context switches across all cores. |
| `procs_running` | `SystemCpuMetrics` | Integer count | `/proc/stat` | `procs_running <n>` | Number of processes currently runnable on CPU runqueues. |
| `procs_blocked` | `SystemCpuMetrics` | Integer count | `/proc/stat` | `procs_blocked <n>` | Number of processes blocked waiting for I/O completion. |

### 2.2 Global CPU Utilization

| Metric Field | Model | Normalized Unit | Exact Data Source | Linux Kernel Interface / API | Description |
|---|---|---|---|---|---|
| `percent` | `SystemCpuMetrics` | Percentage `0.0`–`100.0` | `psutil.cpu_percent` | `/proc/stat` CPU time calculation | Total CPU utilization sampled non-blockingly across cores. |
| `per_cpu_percent` | `SystemCpuMetrics` | List of percentages | `psutil.cpu_percent(percpu=True)` | `/proc/stat` per-core lines | Individual core utilization breakdown ($C_0, C_1, \dots$). |

### 2.3 Physical Memory & Swap

| Metric Field | Model | Normalized Unit | Exact Data Source | Linux Kernel Interface / API | Description |
|---|---|---|---|---|---|
| `total_bytes` | `SystemMemoryMetrics` | Bytes (`int`) | `psutil.virtual_memory().total` | `/proc/meminfo` (`MemTotal`) | Total physical RAM installed on the machine. |
| `available_bytes` | `SystemMemoryMetrics` | Bytes (`int`) | `psutil.virtual_memory().available` | `/proc/meminfo` (`MemAvailable`) | Memory available for starting new applications without swapping. |
| `used_bytes` | `SystemMemoryMetrics` | Bytes (`int`) | `psutil.virtual_memory().used` | Calculated (`total - free - buffers - cache`) | Active and allocated physical memory. |
| `free_bytes` | `SystemMemoryMetrics` | Bytes (`int`) | `psutil.virtual_memory().free` | `/proc/meminfo` (`MemFree`) | Completely unallocated memory. |
| `percent` | `SystemMemoryMetrics` | Percentage `0.0`–`100.0` | `psutil.virtual_memory().percent` | Ratio (`(total - available) / total`) | System RAM consumption percentage. |
| `buffers_bytes` | `SystemMemoryMetrics` | Bytes (`int`) | `/proc/meminfo` | `Buffers: <n> kB` | Kernel memory used for block device disk buffers. |
| `cached_bytes` | `SystemMemoryMetrics` | Bytes (`int`) | `/proc/meminfo` | `Cached: <n> kB` | In-memory page cache holding filesystem data. |
| `swap_total_bytes` | `SystemMemoryMetrics` | Bytes (`int`) | `psutil.swap_memory().total` | `/proc/meminfo` (`SwapTotal`) | Total configured swap space. |
| `swap_used_bytes` | `SystemMemoryMetrics` | Bytes (`int`) | `psutil.swap_memory().used` | `/proc/meminfo` (`SwapTotal - SwapFree`) | Allocated swap space. |
| `swap_percent` | `SystemMemoryMetrics` | Percentage `0.0`–`100.0` | `psutil.swap_memory().percent` | Ratio (`swap_used / swap_total`) | Swap utilization percentage. |

### 2.4 Filesystem Disk Storage

| Metric Field | Model | Normalized Unit | Exact Data Source | Linux Kernel Interface / API | Description |
|---|---|---|---|---|---|
| `mount_point` | `DiskUsageMetrics` | String path (e.g. `"/"`) | `psutil.disk_usage(path)` | `statvfs(2)` syscall | Filesystem mount location. |
| `total_bytes` | `DiskUsageMetrics` | Bytes (`int`) | `psutil.disk_usage().total` | `statvfs.f_blocks * f_frsize` | Total filesystem capacity. |
| `used_bytes` | `DiskUsageMetrics` | Bytes (`int`) | `psutil.disk_usage().used` | `(f_blocks - f_bfree) * f_frsize` | Consumed disk space. |
| `free_bytes` | `DiskUsageMetrics` | Bytes (`int`) | `psutil.disk_usage().free` | `f_bavail * f_frsize` | Free space accessible to unprivileged users. |
| `percent` | `DiskUsageMetrics` | Percentage `0.0`–`100.0` | `psutil.disk_usage().percent` | Syscall ratio | Filesystem usage percentage. |

### 2.5 Supervised Process Telemetry

| Metric Field | Model | Normalized Unit | Exact Data Source | Linux Kernel Interface / API | Description |
|---|---|---|---|---|---|
| `pid` | `ProcessMetrics` | Integer (`> 0`) | `psutil.Process.pid` | Linux OS PID | Unique process identifier. |
| `name` | `ProcessMetrics` | String | `psutil.Process.name` | `/proc/[pid]/comm` | Binary or executable name. |
| `state` | `ProcessMetrics` | `ProcessState` enum | `/proc/[pid]/status` & `proc.status()` | `State: <R/S/D/T/Z/X/I>` in `/proc/[pid]/status` | Execution state: `RUNNING`, `SLEEPING`, `DISK_SLEEP`, `STOPPED`, `ZOMBIE`, `DEAD`, `IDLE`. |
| `ppid` | `ProcessMetrics` | Integer (`>= 0`) | `psutil.Process.ppid` | `/proc/[pid]/status` (`PPid`) | Parent process identifier. |
| `cpu_percent` | `ProcessMetrics` | Percentage (`float`) | `psutil.Process.cpu_percent` | `/proc/[pid]/stat` ticks calculation | Process CPU utilization. |
| `rss_bytes` | `ProcessMetrics` | Bytes (`int`) | `psutil.Process.memory_info().rss` | `/proc/[pid]/status` (`VmRSS`) | Resident Set Size (physical memory occupied by process). |
| `vms_bytes` | `ProcessMetrics` | Bytes (`int`) | `psutil.Process.memory_info().vms` | `/proc/[pid]/status` (`VmSize`) | Virtual Memory Size. |
| `memory_percent` | `ProcessMetrics` | Percentage (`float`) | `psutil.Process.memory_percent` | Ratio (`rss / total_memory`) | Fraction of host physical memory consumed by process. |
| `num_threads` | `ProcessMetrics` | Integer (`>= 1`) | `psutil.Process.num_threads` | `/proc/[pid]/status` (`Threads`) | Active threads inside process. |
| `num_fds` | `ProcessMetrics` | Integer (`>= 0`) | `psutil.Process.num_fds` | `/proc/[pid]/fd` count | Open file descriptors allocated by process. |
| `cmdline` | `ProcessMetrics` | List of strings | `/proc/[pid]/cmdline` | Null-byte separated entries | Complete invocation arguments. |
| `create_time` | `ProcessMetrics` | Seconds (`float`) | `psutil.Process.create_time` | `/proc/[pid]/stat` start time | Epoch timestamp of process initiation. |

### 2.6 Systemd Service Status

| Metric Field | Model | Normalized Unit | Exact Data Source | Inspection Command | Description |
|---|---|---|---|---|---|
| `service_name` | `ServiceMetrics` | String (`.service`) | Verified unit name | — | Sanitized systemd unit name. |
| `is_active` | `ServiceMetrics` | Boolean | `systemctl show -p ActiveState` | `systemctl show ...` | `True` when `ActiveState == "active"`. |
| `active_state` | `ServiceMetrics` | String | `systemctl show -p ActiveState` | `ActiveState=<val>` | State string (`active`, `inactive`, `failed`, `activating`). |
| `sub_state` | `ServiceMetrics` | String | `systemctl show -p SubState` | `SubState=<val>` | Detailed state (`running`, `dead`, `exited`, `start-pre`). |
| `is_enabled` | `ServiceMetrics` | Optional boolean | `systemctl show -p UnitFileState`| `UnitFileState=<val>` | `True` if enabled to start on system boot. |
| `checked_at` | `ServiceMetrics` | UTC datetime | System clock | — | Timestamp of inspection probe. |

---

## 3. CLI Snapshot Command Usage

The CLI command captures and renders an instantaneous system snapshot.

```bash
# Terminal human-readable view:
python -m self_healing monitor

# JSON structured snapshot (suitable for automation/pipelines):
python -m self_healing monitor --json

# Inspect specific systemd services:
python -m self_healing monitor --service cron --service ssh

# Filter process metrics to a registered target:
python -m self_healing monitor --target demo-web
```
