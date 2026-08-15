## Claude Code host execution

- Invoke Skills with `/skill-name` syntax.
- Dispatch a fresh non-fork `polaris-implementer` or `polaris-reviewer` custom subagent through the Agent tool in the shared checkout. Never use a conversation fork or worktree isolation.
- Record the returned agent ID as the worker session attestation and worker reference. Reuse or resume only that exact ID within the current main session; ambiguous identity requires the declared fallback.
- Resume the same Implementer agent ID for `{{skill:documentation-sync}}`. Never reuse an Implementer as a Reviewer or reuse a Reviewer for another slot.
