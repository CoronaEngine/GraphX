---
name: validation
description: Internal Polaris stage for an explicitly started `$engineering-task` workflow. Invoke only in VALIDATING after an accepted Review; do not activate from ordinary validation or test requests.
---

# Validation

1. Confirm the accepted Review matches the current Work Item revision, subject commits, and subject diff hash.
2. Execute the evidence method for every acceptance criterion without weakening it.
3. Record command/check, working directory, environment summary, start time, exit code, result, and output path or hash.
4. Mark the overall verdict PASS only when every acceptance criterion passes.
5. Write a new immutable Validation JSON attempt and readable projection.
6. Use `PASS_VALIDATION`, `FAIL_IMPLEMENTATION`, or `FAIL_PLAN` according to the evidence.
7. Require final Human approval before `CLOSE` when rigor is R2.

Compilation alone is not completion unless it is the only explicit acceptance criterion. Never edit `state.json` or claim `CLOSED` directly.
