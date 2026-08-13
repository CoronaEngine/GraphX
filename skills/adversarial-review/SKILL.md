---
name: adversarial-review
description: Independently and adversarially review a frozen Polaris change package. Use in REVIEWING for R1/R2 independent review or an R0 isolated pass, checking specification compliance first and engineering quality second against the exact subject revision and diff hash.
---

# Adversarial Review

For R1/R2, run only in a fresh Codex session or an isolated reviewer agent created without implementation chat history. If this context implemented the subject or inherited that conversation, stop without reviewing. R0 may use the same session only as an explicit isolated pass.

1. Run `recover_task.py <task-id> --repo . --json` and require state `REVIEWING`.
2. Load the registered `review_handoff` and only its package paths. Do not use implementer explanations or prior chat.
3. Verify handoff hashes, task revision, Review attempt, exact subject commits/diff hash, and the required isolation mode.
4. Assign a reviewer session ID distinct from the implementer for R1/R2. Attest truthfully to isolation and chat-history inheritance; do not fabricate independence.
5. Check specification compliance first: correct problem, scope, exclusions, constraints, and every acceptance criterion.
6. Check engineering quality second: correctness, failure paths, lifetime, concurrency, security, performance, compatibility, maintainability, test gaps, and counterexamples.
7. Preserve every prior Finding ID in a follow-up Review. Read the registered author response, recheck the entire new patch, and record a concrete `reviewer_resolution` for each carried Finding.
8. Give new Findings monotonic IDs and mark critical/high, acceptance failures, and scope violations as blocking.
9. Write a new immutable Review JSON bound to the handoff and session attestation. Reject while any blocking Finding remains open.
10. Use `ACCEPT_REVIEW` or `REJECT_REVIEW`; never modify implementation code during Review. A third rejection enters Human-owned `BLOCKED`.

Only the Reviewer context may write `ACCEPT`.
