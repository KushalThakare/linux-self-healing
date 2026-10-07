"""Isolated demo workload processes for fault injection testing.

Strictly adheres to safety rules:
- Bounded blast radius: targets are isolated Python processes within the repository workspace.
- No interference with host system services or unrelated processes.
- Memory ceiling: strictly capped to prevent system OOM.
- Disk ceiling: strictly capped to prevent partition exhaustion.
"""

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
import os
from pathlib import Path
import signal
import sys
import threading
import time
from typing import List, Optional

# Global flag for graceful termination
_RUNNING = True


def _handle_exit_signal(signum: int, frame: Optional[object]) -> None:
    global _RUNNING
    _RUNNING = False
    sys.stderr.write(f"[DEMO_WORKLOAD] Received signal {signum}, exiting gracefully.\n")
    sys.stderr.flush()
    sys.exit(0)


def setup_signal_handlers() -> None:
    signal.signal(signal.SIGTERM, _handle_exit_signal)
    signal.signal(signal.SIGINT, _handle_exit_signal)


# -------------------------------------------------------------------------
# 1. CPU Runaway Workload
# -------------------------------------------------------------------------
def run_cpu_spin() -> None:
    """Consume ~100% of a single CPU core in an isolated calculation loop."""
    setup_signal_handlers()
    sys.stdout.write(f"[CPU_SPIN] Started on PID {os.getpid()} (single-thread tight loop).\n")
    sys.stdout.flush()

    iterations = 0
    while _RUNNING:
        # Tight CPU-bound arithmetic loop
        for i in range(100_000):
            _ = math.sqrt(i * 1.0001) ** 2
        iterations += 1
        if iterations % 50 == 0:
            sys.stdout.write(f"[CPU_SPIN] Still running... ({iterations} windows processed)\n")
            sys.stdout.flush()


# -------------------------------------------------------------------------
# 2. Memory Growth Workload
# -------------------------------------------------------------------------
def run_memory_leak(max_mb: int = 256, chunk_mb: int = 20, interval_sec: float = 0.5) -> None:
    """Incrementally allocate memory chunks up to a safe maximum ceiling.
    
    Hard safety boundary: strictly capped at max_mb to prevent system OOM.
    """
    setup_signal_handlers()
    sys.stdout.write(
        f"[MEMORY_LEAK] Started on PID {os.getpid()}. Allocating {chunk_mb}MB every {interval_sec}s "
        f"up to safe cap {max_mb}MB.\n"
    )
    sys.stdout.flush()

    chunks: List[bytearray] = []
    total_allocated_mb = 0

    while _RUNNING:
        if total_allocated_mb + chunk_mb <= max_mb:
            # Allocate chunk with non-zero bytes so pages are physically faulted in RSS
            chunk = bytearray(b"\xaa" * (chunk_mb * 1024 * 1024))
            chunks.append(chunk)
            total_allocated_mb += chunk_mb
            sys.stdout.write(f"[MEMORY_LEAK] Allocated {total_allocated_mb} MB / {max_mb} MB limit.\n")
            sys.stdout.flush()
        else:
            # Reached ceiling: maintain allocated memory so RSS remains elevated
            pass
        time.sleep(interval_sec)


# -------------------------------------------------------------------------
# 3. Service Worker Workload
# -------------------------------------------------------------------------
class ServiceHealthHandler(BaseHTTPRequestHandler):
    """Minimal HTTP request handler for the demo service."""

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            payload = json.dumps({"status": "ok", "service": "demo-service", "pid": os.getpid()})
            self.wfile.write(payload.encode("utf-8"))
        elif self.path == "/crash":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Crashing service now...\n")
            sys.stderr.write("[SERVICE_WORKER] Received /crash trigger. Exiting immediately.\n")
            sys.stderr.flush()
            os._exit(1)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        if self.path == "/crash":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Crashing service now...\n")
            sys.stderr.write("[SERVICE_WORKER] Received /crash trigger. Exiting immediately.\n")
            sys.stderr.flush()
            os._exit(1)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        # Suppress noisy standard access logs
        pass


def run_service_worker(host: str = "127.0.0.1", port: int = 8085, auto_crash_after: Optional[float] = None) -> None:
    """Run an isolated lightweight HTTP service with health and crash endpoints."""
    setup_signal_handlers()
    server = HTTPServer((host, port), ServiceHealthHandler)
    server.timeout = 1.0
    sys.stdout.write(f"[SERVICE_WORKER] Listening on http://{host}:{port} (PID: {os.getpid()}).\n")
    sys.stdout.flush()

    start_time = time.time()
    try:
        while _RUNNING:
            server.handle_request()
            if auto_crash_after and (time.time() - start_time >= auto_crash_after):
                sys.stderr.write(f"[SERVICE_WORKER] Auto-crash interval reached ({auto_crash_after}s). Exiting.\n")
                sys.stderr.flush()
                os._exit(1)
    finally:
        server.server_close()


# -------------------------------------------------------------------------
# 4. Disk / Log Growth Workload
# -------------------------------------------------------------------------
def run_disk_write(output_dir: str, max_mb: int = 50, chunk_kb: int = 1024, interval_sec: float = 0.2) -> None:
    """Generate dummy log records rapidly into an isolated directory.
    
    Hard safety boundary: strictly capped at max_mb to avoid filling filesystem.
    """
    setup_signal_handlers()
    target_path = Path(output_dir).resolve()
    target_path.mkdir(parents=True, exist_ok=True)
    log_file = target_path / "demo_disk_growth.log"

    sys.stdout.write(
        f"[DISK_WRITE] Started on PID {os.getpid()}. Writing dummy log entries to {log_file} "
        f"(max: {max_mb}MB, chunk: {chunk_kb}KB).\n"
    )
    sys.stdout.flush()

    chunk_data = ("X" * 1022 + "\n") * (chunk_kb // 1)
    encoded_chunk = chunk_data.encode("utf-8")
    total_written_bytes = 0
    max_bytes = max_mb * 1024 * 1024

    with open(log_file, "a", buffering=1024 * 1024) as f:
        while _RUNNING:
            if total_written_bytes + len(encoded_chunk) <= max_bytes:
                f.write(chunk_data)
                f.flush()
                total_written_bytes += len(encoded_chunk)
                if total_written_bytes % (5 * 1024 * 1024) == 0:
                    written_mb = total_written_bytes / (1024 * 1024)
                    sys.stdout.write(f"[DISK_WRITE] Written {written_mb:.1f} MB / {max_mb} MB limit.\n")
                    sys.stdout.flush()
            else:
                # Reached cap: keep file open without expanding further
                pass
            time.sleep(interval_sec)


# -------------------------------------------------------------------------
# 5. Deadlock Workload
# -------------------------------------------------------------------------
def run_deadlock_hang() -> None:
    """Induce an AB-BA circular lock dependency in worker threads."""
    setup_signal_handlers()
    lock_a = threading.Lock()
    lock_b = threading.Lock()

    ready_event = threading.Event()

    def worker_one() -> None:
        with lock_a:
            sys.stdout.write("[DEADLOCK] Thread 1 acquired Lock A, waiting for sync...\n")
            sys.stdout.flush()
            ready_event.set()
            time.sleep(0.1)
            sys.stdout.write("[DEADLOCK] Thread 1 attempting to acquire Lock B...\n")
            sys.stdout.flush()
            with lock_b:
                pass

    def worker_two() -> None:
        ready_event.wait(timeout=2.0)
        with lock_b:
            sys.stdout.write("[DEADLOCK] Thread 2 acquired Lock B, attempting to acquire Lock A...\n")
            sys.stdout.flush()
            with lock_a:
                pass

    t1 = threading.Thread(target=worker_one, name="DeadlockThread-1", daemon=True)
    t2 = threading.Thread(target=worker_two, name="DeadlockThread-2", daemon=True)

    t1.start()
    t2.start()

    sys.stdout.write(f"[DEADLOCK] Deadlock initialized on PID {os.getpid()}. Threads are now hung.\n")
    sys.stdout.flush()

    # Main thread sleeps cleanly waiting for signals
    while _RUNNING:
        time.sleep(0.5)


# -------------------------------------------------------------------------
# CLI Dispatcher for Demo Workloads
# -------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Isolated demo workloads for fault injection.")
    subparsers = parser.add_subparsers(dest="workload", required=True)

    # 1. cpu_spin
    subparsers.add_parser("cpu_spin", help="Spin 1 CPU core in a tight loop")

    # 2. memory_leak
    p_mem = subparsers.add_parser("memory_leak", help="Incrementally allocate memory")
    p_mem.add_argument("--max-mb", type=int, default=256, help="Maximum memory allocation cap in MB")
    p_mem.add_argument("--chunk-mb", type=int, default=20, help="Chunk size in MB")
    p_mem.add_argument("--interval", type=float, default=0.5, help="Allocation interval in seconds")

    # 3. service_worker
    p_svc = subparsers.add_parser("service_worker", help="Lightweight HTTP service")
    p_svc.add_argument("--host", default="127.0.0.1", help="Host interface")
    p_svc.add_argument("--port", type=int, default=8085, help="Port to listen on")
    p_svc.add_argument("--auto-crash-after", type=float, default=None, help="Auto crash after N seconds")

    # 4. disk_write
    p_disk = subparsers.add_parser("disk_write", help="Generate log entries rapidly")
    p_disk.add_argument("--dir", default="demo_scratch/logs", help="Output directory")
    p_disk.add_argument("--max-mb", type=int, default=50, help="Maximum disk usage cap in MB")
    p_disk.add_argument("--interval", type=float, default=0.2, help="Write interval in seconds")

    # 5. deadlock_hang
    subparsers.add_parser("deadlock_hang", help="Hang in circular mutex deadlock")

    args = parser.parse_args()

    if args.workload == "cpu_spin":
        run_cpu_spin()
    elif args.workload == "memory_leak":
        run_memory_leak(max_mb=args.max_mb, chunk_mb=args.chunk_mb, interval_sec=args.interval)
    elif args.workload == "service_worker":
        run_service_worker(host=args.host, port=args.port, auto_crash_after=args.auto_crash_after)
    elif args.workload == "disk_write":
        run_disk_write(output_dir=args.dir, max_mb=args.max_mb, interval_sec=args.interval)
    elif args.workload == "deadlock_hang":
        run_deadlock_hang()
    else:
        sys.stderr.write(f"Unknown workload: {args.workload}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
