---
name: documentation-sync
description: Internal Polaris stage for an explicitly started `$engineering-task` workflow. Invoke only in IMPLEMENTED or after implementation rework to reconcile documentation; do not activate from ordinary documentation requests.
---

# Documentation Sync

1. Compare changed subject paths with project documentation and the frozen Work Item.
2. Write a Knowledge Delta JSON with an entry for every affected knowledge area: `ADD`, `UPDATE`, `STALE`, or `NO_CHANGE`.
3. Update confirmed project documentation. Do not promote unverified inference to authority.
4. Record failed attempts with `record_exploration.py`. Keep task-only conclusions in the task; promote reusable, evidence-backed conclusions to `.polaris/explorations/` with the same script.
5. Leave no unresolved `STALE` entry.
6. Create the final subject checkpoint and recompute the subject diff hash.
7. Refresh the Working Set if a promoted exploration or documentation change alters the next stage's justified inputs.
8. Run `check_docs.py`, then transition with `SYNC_DOCS`.

Do not edit Review, Validation, Result, event, or state artifacts directly.
