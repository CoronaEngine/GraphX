---
name: validation
description: Internal Polaris stage for an explicitly started `{{skill:engineering-task}}` workflow. Invoke only in VALIDATING after an accepted Review; do not activate from ordinary validation or test requests.
---

# Validation

1. Confirm the accepted Review matches the current Work Item revision, subject commits, and subject diff hash.
2. Execute the evidence method for every acceptance criterion without weakening it. Do not invoke Code Intelligence during Validation or use provider observations as acceptance evidence; rely on source, Git, builds, tests, static checks, and Human Checks.
3. Record command/check, working directory, environment summary, start time, exit code, result, and output path or hash.
4. Mark the overall verdict PASS only when every acceptance criterion passes.
5. Write a new immutable Validation JSON attempt. Do not create a duplicate Markdown artifact.
6. On PASS, write the immutable Result JSON bound to the same revision and subject. For R0/R1, submit Validation and Result together with `PASS_AND_CLOSE`. For R2, submit Validation with `PASS_VALIDATION`, require final Human approval, then submit Result and approval with `CLOSE`.
7. On FAIL, use `FAIL_IMPLEMENTATION` or `FAIL_PLAN` according to the evidence.

After the transition succeeds, reload state and emit `[POLARIS:VALIDATION_PASS]` or `[POLARIS:VALIDATION_FAIL]` with the nine fixed `{{skill:engineering-task}}` status fields. Include one result per acceptance ID, its evidence path or hash, the Validation path, Result path on PASS, and the next legal transition. For R0/R1, emit `[POLARIS:TASK_CLOSED]` only after `PASS_AND_CLOSE` succeeds. For R2, emit it only after the later `CLOSE` succeeds.

Compilation alone is not completion unless it is the only explicit acceptance criterion. Never edit `state.json` or claim `CLOSED` directly.
