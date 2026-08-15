# Claude Code repository instructions

@AGENTS.md

- `AGENTS.md` above is the shared repository engineering authority.
- In Claude Code, invoke Polaris Skills with slash syntax: `/engineering-task`, `/requirement-analysis`, `/architecture-planning`, `/implementation`, `/documentation-sync`, `/adversarial-review`, and `/validation`.
- Enter Polaris only when the user explicitly invokes `/engineering-task`; ordinary engineering requests do not opt in.
- For an authorized R1/R2 workflow, let `/engineering-task` delegate to the vendored non-fork `polaris-implementer` and `polaris-reviewer` subagents. They share the current checkout but start with fresh context.
- Resume the same Implementer agent for Documentation Sync. Never reuse an Implementer as a Reviewer, and never use a fork that inherits implementation chat for Review.
