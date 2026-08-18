---
name: adversarial-review
description: Internal Polaris review stage for an explicitly started `{{skill:engineering-task}}` workflow. Invoke only from a registered REVIEWING handoff for R1/R2 independent review or an R0 isolated pass; do not activate from ordinary review requests.
---

# Adversarial Review

For R1/R2, run only in the fresh Reviewer context defined by the active host adapter, without implementation chat history. If this context implemented the subject or inherited that conversation, stop without reviewing. R0 may use the same session only as an explicit isolated pass.

1. Run `recover_task.py <task-id> --repo . --json` and require state `REVIEWING`.
2. Require an explicit Reviewer slot and registered `review_handoff` path from the dispatcher. Load only that handoff and its package paths. Do not use implementer explanations, prior chat, another Reviewer's artifact, or an expected verdict.
3. Verify handoff hashes, task revision, Review attempt, exact subject commits/diff hash, and the required isolation mode.
4. Assign a reviewer session ID distinct from the implementer for R1/R2. Attest truthfully to isolation and chat-history inheritance; do not fabricate independence. At the Review boundary invoke `{{skill:code-intelligence}}` for optional independent registered-subject relationships, first using `status` or `sync-if-needed`. Use CodeGraph only with an existing `.codegraph/` directory: prefer `codegraph_explore`, with `codegraph explore` as the non-MCP fallback. A bounded `codegraph sync` is non-blocking. Do not reuse Implementer query conclusions. Missing or failing Provider output immediately falls back to the original frozen-package and source review.
5. Check specification compliance first: correct problem, scope, exclusions, constraints, and every acceptance criterion.
6. Check engineering quality second: correctness, failure paths, lifetime, concurrency, security, performance, compatibility, maintainability, test gaps, and counterexamples.
7. Preserve every prior Finding ID in a follow-up Review. Read the registered author response, recheck the entire new patch, and record a concrete `reviewer_resolution` for each carried Finding.
8. Give new Findings monotonic IDs and mark critical/high, acceptance failures, and scope violations as blocking.
9. Finalize an immutable v2 Review Code Intelligence record, including `UNAVAILABLE`, `FAILED`, or `SKIPPED` when appropriate. Resolve the output with `task_layout.review_path` from the handoff revision, attempt, and Reviewer slot. Write a new immutable Review JSON bound to the handoff, slot, session attestation, and optional record. Never assemble the path independently or overwrite an existing artifact. Reject while any blocking Finding remains open; Code Intelligence cannot determine the verdict.
10. Return the verdict and exact Review path to the dispatching `{{skill:engineering-task}}` context. Do not run `ACCEPT_REVIEW` or `REJECT_REVIEW`; the dispatcher validates and registers all required Review artifacts before applying the graph transition. Never modify implementation code or start another Reviewer task during Review.

Return a concise structured result to the dispatcher with verdict, Review attempt, Reviewer slot, reviewer session ID, subject commits/diff hash, every Finding ID and status, and the immutable Review path. Do not emit a Polaris checkpoint marker from the child task. The dispatching context emits `[POLARIS:REVIEW_ACCEPTED]` or `[POLARIS:REVIEW_REJECTED]` with the nine fixed fields only after the corresponding transition succeeds. If isolation or handoff validation prevents review, do not write a Review; report the exact required fresh-session or handoff action to the dispatcher.

Only the Reviewer context may write `ACCEPT`.

CodeGraph fallback contract: never run `codegraph init` or manage the Provider. Save and classify each response; when `RESPONSE_BANNER` is present, persist its successful explore response hash as `freshness.response_sha256`. For `PARTIAL_STALE`, if a named path is a current confined regular file, directly read it and record `READ_SOURCE` with its current SHA-256; if a safe path is missing/deleted, inspect the registered subject Git diff and record `INSPECT_GIT_DIFF` with null observed SHA-256 and bound base/head/diff evidence; for unsafe paths, record `NOT_VERIFIED` and use source search. For `INDEX_STALE` or `NOT_VERIFIED`, use source search and Git evidence, then stop graph calls for this stage. Each `SEARCH_SOURCE` fallback records `result_paths`: zero or at most 100 unique POSIX paths, each a current confined regular file with its current SHA-256; non-`SEARCH_SOURCE` fallbacks use empty `result_paths`. Graph evidence cannot determine the Review verdict.
