"""Publication-grade visualization generator for experimental evaluation."""

from pathlib import Path
from typing import Dict, List
import matplotlib
matplotlib.use("Agg")  # Non-interactive headless backend
import matplotlib.pyplot as plt
import numpy as np

from self_healing.evaluation.models import (
    DetectionMode,
    EvaluatedFaultType,
    ModeSummary,
    TrialResult,
)


def generate_all_plots(
    rule_summary: ModeSummary,
    hybrid_summary: ModeSummary,
    trials: List[TrialResult],
    output_dir: Path,
) -> List[Path]:
    """Generate all research-grade report plots in output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_files: List[Path] = []

    # Modern clean styling matching the design philosophy
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Helvetica", "Arial"]
    plt.rcParams["axes.edgecolor"] = "#CCCCCC"
    plt.rcParams["axes.linewidth"] = 0.8
    plt.rcParams["grid.color"] = "#EAEAEA"
    plt.rcParams["grid.linestyle"] = "--"
    plt.rcParams["grid.alpha"] = 0.7

    color_rule = "#1D4ED8"     # Technical cobalt blue
    color_hybrid = "#0D9488"   # Teal / Emerald
    color_accent = "#D97706"   # Amber accent

    fault_keys = ["cpu", "memory", "service", "disk", "deadlock"]
    fault_labels = ["CPU Runaway", "Memory Leak", "Service Crash", "Disk Fill", "Deadlock"]

    # -------------------------------------------------------------------------
    # Plot 1: Detection Latency Comparison (ms)
    # -------------------------------------------------------------------------
    p1 = output_dir / "detection_latency_comparison.png"
    fig, ax = plt.subplots(figsize=(9, 5), dpi=300)

    rule_means = [rule_summary.by_fault_detection_latency_ms.get(k, None) for k in fault_keys]
    hybrid_means = [hybrid_summary.by_fault_detection_latency_ms.get(k, None) for k in fault_keys]

    r_vals = [s.mean if s else 0.0 for s in rule_means]
    r_errs = [s.std_dev if s else 0.0 for s in rule_means]
    h_vals = [s.mean if s else 0.0 for s in hybrid_means]
    h_errs = [s.std_dev if s else 0.0 for s in hybrid_means]

    x = np.arange(len(fault_labels))
    width = 0.35

    rects1 = ax.bar(x - width/2, r_vals, width, yerr=r_errs, capsize=4, label="Deterministic Rule-Based", color=color_rule, alpha=0.9)
    rects2 = ax.bar(x + width/2, h_vals, width, yerr=h_errs, capsize=4, label="Rule + Isolation Forest", color=color_hybrid, alpha=0.9)

    ax.set_ylabel("Detection Latency (ms)", fontsize=11, fontweight="bold")
    ax.set_title("Detection Latency by Fault Condition (Mean ± Std Dev)", fontsize=13, fontweight="bold", pad=12)
    ax.set_xticks(x)
    ax.set_xticklabels(fault_labels, fontsize=10)
    ax.legend(frameon=True, facecolor="#FAFAFA", edgecolor="#E5E5E5")
    ax.grid(axis="y")

    # Add numeric labels
    for rect in rects1:
        h = rect.get_height()
        if h > 0:
            ax.annotate(f"{h:.0f}ms", xy=(rect.get_x() + rect.get_width()/2, h),
                        xytext=(0, 4), textcoords="offset points", ha="center", va="bottom", fontsize=8)
    for rect in rects2:
        h = rect.get_height()
        if h > 0:
            ax.annotate(f"{h:.0f}ms", xy=(rect.get_x() + rect.get_width()/2, h),
                        xytext=(0, 4), textcoords="offset points", ha="center", va="bottom", fontsize=8)

    fig.tight_layout()
    fig.savefig(p1)
    plt.close(fig)
    generated_files.append(p1)

    # -------------------------------------------------------------------------
    # Plot 2: Total Recovery Time (MTTR in Seconds)
    # -------------------------------------------------------------------------
    p2 = output_dir / "total_recovery_time_comparison.png"
    fig, ax = plt.subplots(figsize=(9, 5), dpi=300)

    r_tot = [rule_summary.by_fault_total_recovery_time_s.get(k, None) for k in fault_keys]
    h_tot = [hybrid_summary.by_fault_total_recovery_time_s.get(k, None) for k in fault_keys]

    r_tot_vals = [s.mean if s else 0.0 for s in r_tot]
    r_tot_errs = [s.std_dev if s else 0.0 for s in r_tot]
    h_tot_vals = [s.mean if s else 0.0 for s in h_tot]
    h_tot_errs = [s.std_dev if s else 0.0 for s in h_tot]

    rects1 = ax.bar(x - width/2, r_tot_vals, width, yerr=r_tot_errs, capsize=4, label="Deterministic Rule-Based", color=color_rule, alpha=0.9)
    rects2 = ax.bar(x + width/2, h_tot_vals, width, yerr=h_tot_errs, capsize=4, label="Rule + Isolation Forest", color=color_hybrid, alpha=0.9)

    ax.set_ylabel("Total Recovery Time (seconds)", fontsize=11, fontweight="bold")
    ax.set_title("End-to-End Mean Time To Recovery (MTTR) by Fault", fontsize=13, fontweight="bold", pad=12)
    ax.set_xticks(x)
    ax.set_xticklabels(fault_labels, fontsize=10)
    ax.legend(frameon=True, facecolor="#FAFAFA", edgecolor="#E5E5E5")
    ax.grid(axis="y")

    for rect in rects1:
        h = rect.get_height()
        if h > 0:
            ax.annotate(f"{h:.2f}s", xy=(rect.get_x() + rect.get_width()/2, h),
                        xytext=(0, 4), textcoords="offset points", ha="center", va="bottom", fontsize=8)
    for rect in rects2:
        h = rect.get_height()
        if h > 0:
            ax.annotate(f"{h:.2f}s", xy=(rect.get_x() + rect.get_width()/2, h),
                        xytext=(0, 4), textcoords="offset points", ha="center", va="bottom", fontsize=8)

    fig.tight_layout()
    fig.savefig(p2)
    plt.close(fig)
    generated_files.append(p2)

    # -------------------------------------------------------------------------
    # Plot 3: Dependability & Safety Rates Comparison
    # -------------------------------------------------------------------------
    p3 = output_dir / "dependability_metrics_matrix.png"
    fig, ax = plt.subplots(figsize=(9, 5), dpi=300)

    metric_names = [
        "Detection Rate",
        "Recovery Success",
        "Verification Pass",
        "Guardrail Approval",
        "False Positive Rate",
    ]
    r_rates = [
        rule_summary.detection_success_rate_percent,
        rule_summary.recovery_success_rate_percent,
        rule_summary.verification_success_rate_percent,
        rule_summary.guardrail_approval_rate_percent,
        rule_summary.false_positive_rate_percent,
    ]
    h_rates = [
        hybrid_summary.detection_success_rate_percent,
        hybrid_summary.recovery_success_rate_percent,
        hybrid_summary.verification_success_rate_percent,
        hybrid_summary.guardrail_approval_rate_percent,
        hybrid_summary.false_positive_rate_percent,
    ]

    x3 = np.arange(len(metric_names))
    rects1 = ax.bar(x3 - width/2, r_rates, width, label="Deterministic Rule-Based", color=color_rule, alpha=0.9)
    rects2 = ax.bar(x3 + width/2, h_rates, width, label="Rule + Isolation Forest", color=color_hybrid, alpha=0.9)

    ax.set_ylabel("Rate (%)", fontsize=11, fontweight="bold")
    ax.set_title("Dependability, Verification & Safety Policy Rates", fontsize=13, fontweight="bold", pad=12)
    ax.set_xticks(x3)
    ax.set_xticklabels(metric_names, fontsize=9.5)
    ax.set_ylim(0, 115)
    ax.legend(frameon=True, facecolor="#FAFAFA", edgecolor="#E5E5E5")
    ax.grid(axis="y")

    for rect in rects1:
        h = rect.get_height()
        ax.annotate(f"{h:.1f}%", xy=(rect.get_x() + rect.get_width()/2, h),
                    xytext=(0, 4), textcoords="offset points", ha="center", va="bottom", fontsize=8)
    for rect in rects2:
        h = rect.get_height()
        ax.annotate(f"{h:.1f}%", xy=(rect.get_x() + rect.get_width()/2, h),
                    xytext=(0, 4), textcoords="offset points", ha="center", va="bottom", fontsize=8)

    fig.tight_layout()
    fig.savefig(p3)
    plt.close(fig)
    generated_files.append(p3)

    # -------------------------------------------------------------------------
    # Plot 4: Native Recovery Action Execution Latency (ms)
    # -------------------------------------------------------------------------
    p4 = output_dir / "recovery_latency_by_action.png"
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=300)

    # Aggregate recovery latencies by action type
    action_latencies: Dict[str, List[float]] = {}
    for t in trials:
        if t.action_type and t.recovery_latency_ms is not None:
            action_latencies.setdefault(t.action_type, []).append(t.recovery_latency_ms)

    if action_latencies:
        actions = sorted(action_latencies.keys())
        means = [float(np.mean(action_latencies[a])) for a in actions]
        stds = [float(np.std(action_latencies[a])) for a in actions]

        y_pos = np.arange(len(actions))
        bars = ax.barh(y_pos, means, xerr=stds, align="center", color="#3B82F6", alpha=0.85, capsize=4)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(actions, fontsize=10)
        ax.invert_yaxis()  # Labels read top-to-bottom
        ax.set_xlabel("Execution Latency (ms)", fontsize=11, fontweight="bold")
        ax.set_title("Native Typed Recovery Action Latency", fontsize=13, fontweight="bold", pad=12)
        ax.grid(axis="x")

        for bar in bars:
            w = bar.get_width()
            ax.annotate(f"{w:.2f}ms", xy=(w, bar.get_y() + bar.get_height()/2),
                        xytext=(6, 0), textcoords="offset points", ha="left", va="center", fontsize=9)

        fig.tight_layout()
        fig.savefig(p4)
        plt.close(fig)
        generated_files.append(p4)

    return generated_files
