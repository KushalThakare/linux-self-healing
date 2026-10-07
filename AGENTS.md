We are building a research project called:

"Autonomous Fault Detection and Self-Healing System for Linux"

The project is a user-space Linux self-healing framework running inside an Ubuntu VM.

Core loop:

MONITOR → DETECT → DIAGNOSE → GUARDRAIL → HEAL → VERIFY

IMPORTANT DEVELOPMENT RULES:

1. This is a safety-sensitive system because it can terminate processes,
   restart services, change process priority, and modify system state.

2. NEVER implement arbitrary shell-command execution as the recovery mechanism.

3. Recovery actions must use a typed, allowlisted action registry.

4. Every recovery action must pass through a guardrail/policy layer.

5. Never allow the AI/agent to invent arbitrary Linux commands for recovery.

6. Start with controlled demo processes/services rather than modifying
   unrelated host processes.

7. Every healing action must produce an incident record.

8. Every healing action must be followed by verification.

9. Detection and recovery must remain separate modules.

10. Do not implement Isolation Forest before the deterministic rule-based
    detection pipeline works correctly.

11. Prefer simple, testable Python modules over unnecessarily complex
    frameworks.

12. Do not rewrite working components unless there is a clear reason.

13. Before modifying existing code, inspect the repository structure and
    understand the existing architecture.

14. After every implementation task:
    - run tests
    - run relevant manual verification
    - report failures
    - do not claim success without evidence

15. Keep a clear separation between:
    - monitoring
    - detection
    - diagnosis
    - policy/guardrails
    - recovery
    - verification
    - incident storage
    - API/dashboard

16. The system must be capable of operating in DRY-RUN mode where recovery
    actions are logged but not executed.

17. All dangerous operations must be explicitly restricted to approved
    demo targets.

18. Do not modify the Linux kernel.

19. This is a user-space Linux project.

20. Maintain documentation as the system evolves.

Before implementing anything substantial, create a proposed architecture
and implementation plan and wait for approval.
