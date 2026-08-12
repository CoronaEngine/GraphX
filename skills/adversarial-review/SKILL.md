---
name: adversarial-review
description: Independently and adversarially review a frozen Polaris change package. Use in REVIEWING for R1/R2 independent review or an R0 isolated pass, checking specification compliance first and engineering quality second against the exact subject revision and diff hash.
---

# Adversarial Review

Use only the frozen Work Item, Plan, Working Set, project rules, relevant docs, implementation record, Knowledge Delta, exact subject diff, and reproducible evidence. Do not inherit or rely on the implementer's explanations outside these artifacts.

1. Verify task revision, subject commits, diff hash, and reviewer independence requirements.
2. Check specification compliance: correct problem, scope, exclusions, constraints, and every acceptance criterion.
3. Check engineering quality: correctness, failure paths, lifetime, concurrency, security, performance, compatibility, maintainability, and test gaps.
4. Try to falsify the claim that the patch satisfies the Work Item.
5. Record stable findings with ID, severity, location, claim, evidence, required action, and status.
6. Reject for any critical/high finding, unmet acceptance criterion, or scope violation.
7. Write a new immutable Review JSON attempt and readable projection.
8. Use `ACCEPT_REVIEW` or `REJECT_REVIEW`; never modify implementation code during Review.

After a fix, review the entire new subject patch, not only previous findings.
