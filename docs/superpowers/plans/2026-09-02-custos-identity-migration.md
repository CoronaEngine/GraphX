# Rename Polaris to Custos Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the project from Polaris to Custos across repository content, the GitHub repository, the Git remote, and the local checkout directory.

**Architecture:** This is an identity-only migration: product behavior and architecture remain unchanged while display names become `Custos`, machine identifiers become `custos`, and the repository path becomes `/Users/zero/Documents/work/ai/Custos`. GitHub is renamed only after local content has been updated and checked, and the local directory is renamed last so command working directories remain stable during edits.

**Tech Stack:** Markdown, Git, GitHub CLI, POSIX filesystem operations

**Spec:** `plan.md`

## Global Constraints

- Preserve all product scope, architecture, state-machine, storage, scheduling, and validation requirements in `plan.md`.
- Replace the display name `Polaris` with `Custos` and machine identifier `polaris` with `custos`.
- Preserve Git history and the existing `origin` remote role.
- Rename GitHub repository `CoronaEngine/Polaris` to `CoronaEngine/Custos`.
- Rename local directory `/Users/zero/Documents/work/ai/Polaris` to `/Users/zero/Documents/work/ai/Custos`.

---

### Task 1: Rename repository content

**Files:**
- Modify: `.gitignore`
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `plan.md`
- Create: `docs/superpowers/plans/2026-09-02-custos-identity-migration.md`

**Interfaces:**
- Consumes: The existing project naming conventions documented in `plan.md` and the README files.
- Produces: Consistent `Custos` display names, `custos` Python/tool identifiers, and `.custos/` local-state naming.

- [x] **Step 1: Replace display-name references**

Run a repository-wide textual replacement from `Polaris` to `Custos` in the five existing text files.

- [x] **Step 2: Replace machine identifiers**

Run a repository-wide textual replacement from `polaris` to `custos` in the same files, covering `src/custos/`, `custos_*` MCP operations, and `.custos/` ignored state.

- [x] **Step 3: Verify no legacy references remain**

Run: `rg -n --hidden -i --glob '!.git/**' --glob '!.codegraph/**' --glob '!docs/superpowers/plans/**' 'polaris' .`

Expected: exit code 1 and no output.

- [x] **Step 4: Review the content diff**

Run: `git diff --check && git diff -- .gitignore AGENTS.md README.md README.zh-CN.md plan.md`

Expected: exit code 0, no whitespace errors, and only project-identity substitutions.

### Task 2: Rename the GitHub repository and origin URL

**Files:**
- Modify: `.git/config` through `git remote set-url`

**Interfaces:**
- Consumes: Authenticated GitHub CLI access to `CoronaEngine/Polaris` and the absence of `CoronaEngine/Custos`.
- Produces: GitHub repository `CoronaEngine/Custos` and origin URL `https://github.com/CoronaEngine/Custos.git`.

- [x] **Step 1: Rename the GitHub repository**

Run: `gh repo rename Custos --repo CoronaEngine/Polaris --yes`

Expected: exit code 0.

- [x] **Step 2: Set the canonical origin URL**

Run: `git remote set-url origin https://github.com/CoronaEngine/Custos.git`

Expected: exit code 0.

- [x] **Step 3: Verify remote identity and connectivity**

Run: `gh repo view CoronaEngine/Custos --json nameWithOwner,url && git remote -v && git ls-remote --exit-code origin HEAD`

Expected: GitHub reports `CoronaEngine/Custos`, both origin URLs use `Custos.git`, and remote HEAD resolves.

### Task 3: Rename the local checkout directory

**Files:**
- Move: `/Users/zero/Documents/work/ai/Polaris` to `/Users/zero/Documents/work/ai/Custos`

**Interfaces:**
- Consumes: A nonexistent `/Users/zero/Documents/work/ai/Custos` destination and the updated repository content.
- Produces: A working Git checkout rooted at `/Users/zero/Documents/work/ai/Custos`.

- [x] **Step 1: Confirm the destination is unused**

Run: `test ! -e /Users/zero/Documents/work/ai/Custos`

Expected: exit code 0.

- [x] **Step 2: Rename the directory**

Run from `/Users/zero/Documents/work/ai`: `mv Polaris Custos`

Expected: exit code 0.

- [x] **Step 3: Verify the final checkout**

Run from `/Users/zero/Documents/work/ai/Custos`: `pwd -P && git status --short --branch && git remote -v && rg -n --hidden -i --glob '!.git/**' --glob '!.codegraph/**' --glob '!docs/superpowers/plans/**' 'polaris' .`

Expected: the physical path ends in `/Custos`, Git status reports branch `refactor`, origin uses `CoronaEngine/Custos.git`, and the final search exits 1 with no matches.
