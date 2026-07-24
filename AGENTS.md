# Agents

For development setup, see [docs/development.md](docs/development.md).

For documentation overview, see [docs/docs-overview.md](docs/docs-overview.md).

Before adding or upgrading any dependency, read
[SUPPLY-CHAIN-SECURITY.md](SUPPLY-CHAIN-SECURITY.md) (14-day cool-off, frozen lockfile,
pinned runners).


<!-- BEGIN TBD INTEGRATION -->
---
title: tbd Workflow
description: Full tbd workflow guide for agents
---
**`tbd` helps humans and agents ship code with greater speed, quality, and discipline.**

1. **Beads**: Git-native issue tracking (tasks, bugs, features).
   Never lose work across sessions.
2. **Spec-Driven Workflows**: Plan features → break into beads → implement
   systematically.
3. **Shortcuts**: Reusable instruction templates for common workflows.
4. **Guidelines**: Coding rules and best practices.

## Installation

```bash
npm install -g get-tbd@latest
tbd setup --auto --prefix=<name>   # Fresh project (--prefix is REQUIRED and should be short. For new project setup, ALWAYS ASK THE USER FOR THE PREFIX; do not guess it)
tbd setup --auto                   # Existing tbd project (prefix already set)
tbd setup --from-beads             # Migration from .beads/ if `bd` has been used
```

## Routine Commands

```bash
tbd --help    # Command reference
tbd status    # Status
tbd doctor    # If there are problems

tbd setup --auto   # Run any time to refresh setup
tbd prime      # Restore full context on tbd after compaction
```

## CRITICAL: You Operate tbd — The User Doesn’t

**You are the tbd operator:** Users talk naturally; you translate their requests to tbd
actions. DO NOT tell users to run tbd commands.
That’s your job.

- **WRONG**: "Run `tbd create` to track this bug"

- **RIGHT**: *(you run `tbd create` yourself and tell the user it’s tracked)*

**Welcoming a user:** When users ask “what is tbd?”
or want help → run `tbd shortcut welcome-user`

## User Request → Agent Action

| User Says | You (the Agent) Run |
| --- | --- |
| "There's a bug where ..." | `tbd create "..." --type=bug` |
| "Let's work on issues" | `tbd ready` |
| "Build a TypeScript CLI" | `tbd guidelines typescript-cli-tool-rules` |
| "Improve eslint/monorepo" | `tbd guidelines typescript-monorepo-patterns` |
| "Add e2e/golden testing" | `tbd guidelines golden-testing-guidelines` |
| "Review changes" (TS) | `tbd guidelines typescript-rules` |
| "Review changes" (Python) | `tbd guidelines python-rules` |
| "Plan a new feature" | `tbd shortcut new-plan-spec` |
| "Break spec into beads" | `tbd shortcut plan-implementation-with-beads` |
| "Implement these beads" | `tbd shortcut implement-beads` |
| "Commit this" | `tbd shortcut commit-code` |
| "Create a PR" | `tbd shortcut create-or-update-pr-simple` |
| "Research this topic" | `tbd shortcut new-research-brief` |
| "Document architecture" | `tbd shortcut new-architecture-doc` |
| *(your choice whenever appropriate)* | `tbd list`, `tbd dep add`, `tbd close`, `tbd sync`, etc. |

## CRITICAL: Session Closing Protocol

**Before saying “done”, you MUST complete this checklist:**

```
[ ] 1. git add + git commit
[ ] 2. git push
[ ] 3. gh pr checks <PR> --watch 2>&1 (IMPORTANT: WAIT for final summary, do NOT tell user it is done until you confirm it passes CI!)
[ ] 4. tbd close/update <id> for all beads worked on
[ ] 5. tbd sync
[ ] 6. CONFIRM CI passed (if failed: fix, run tests, re-push, restart from step 3)
```

**Work is not done until pushed, CI passes, and tbd is synced.**

## Bead Tracking Rules

- Track all task work not done immediately as beads (discovered work, TODOs,
  multi-session work)
- When in doubt, create a bead
- Check `tbd ready` when not given specific directions
- Always close/update beads and run `tbd sync` at session end

## Commands

### Finding Work

| Command | Purpose |
| --- | --- |
| `tbd ready` | Beads ready to work (no blockers) |
| `tbd list --status open` | All open beads |
| `tbd list --status in_progress` | Your active work |
| `tbd show <id>` | Bead details with dependencies |

### Creating & Updating

| Command | Purpose |
| --- | --- |
| `tbd create "title" --type task\|bug\|feature --priority=P2` | New bead (P0-P4, not "high/medium/low") |
| `tbd update <id> --status in_progress` | Claim work |
| `tbd close <id> [--reason "..."]` | Mark complete |

### Dependencies & Sync

| Command | Purpose |
| --- | --- |
| `tbd dep add <bead> <depends-on>` | Add dependency |
| `tbd blocked` | Show blocked beads |
| `tbd sync` | Sync with git remote (run at session end) |
| `tbd stats` | Project statistics |
| `tbd doctor` | Check for problems |

### Documentation

| Command | Purpose |
| --- | --- |
| `tbd shortcut <name>` | Run a shortcut |
| `tbd shortcut --list` | List shortcuts |
| `tbd guidelines <name>` | Load coding guidelines |
| `tbd guidelines --list` | List guidelines |
| `tbd template <name>` | Output a template |

## Quick Reference

- **Priority**: P0=critical, P1=high, P2=medium (default), P3=low, P4=backlog
- **Types**: task, bug, feature, epic
- **Status**: open, in_progress, closed
- **JSON output**: Add `--json` to any command

<!-- BEGIN SHORTCUT DIRECTORY -->
## Available Shortcuts

Run `tbd shortcut <name>` to use any of these shortcuts:

| Name | Description |
| --- | --- |
| agent-handoff | Generate a concise handoff prompt for another coding agent to continue work |
| cleanup-all | Full cleanup cycle including duplicate removal, dead code, and code quality improvements |
| cleanup-remove-trivial-tests | Review and remove tests that do not add meaningful coverage |
| cleanup-update-docstrings | Review and add concise docstrings to major functions and types |
| commit-code | Run pre-commit checks, review changes, and commit code |
| create-or-update-pr-simple | Create or update a pull request with a concise summary |
| create-or-update-pr-with-validation-plan | Create or update a pull request with a detailed test/validation plan |
| implement-beads | Implement beads from a spec, following TDD and project rules |
| merge-upstream | Merge origin/main into current branch with conflict resolution |
| new-architecture-doc | Create an architecture document for a system or component design |
| new-guideline | Create a new coding guideline document for tbd |
| new-plan-spec | Create a new feature planning specification document |
| new-research-brief | Create a research document for investigating a topic or technology |
| new-shortcut | Create a new shortcut (reusable instruction template) for tbd |
| new-validation-plan | Create a validation/test plan showing what's tested and what remains |
| plan-implementation-with-beads | Create implementation beads from a feature planning spec |
| precommit-process | Full pre-commit checklist including spec sync, code review, and testing |
| review-code | Comprehensive code review for uncommitted changes, branch work, or GitHub PRs |
| review-code-python | Python-focused code review (language-specific rules only) |
| review-code-typescript | TypeScript-focused code review (language-specific rules only) |
| review-github-pr | Review a GitHub pull request with follow-up actions (comment, fix, CI check) |
| revise-all-architecture-docs | Comprehensive revision of all current architecture documents |
| revise-architecture-doc | Update an architecture document to reflect current codebase state |
| setup-github-cli | Ensure GitHub CLI (gh) is installed and working |
| sync-failure-recovery | Handle tbd sync failures by saving to workspace and recovering later |
| update-specs-status | Review active specs and sync their status with tbd issues |
| welcome-user | Welcome message for users after tbd installation or setup |

## Available Guidelines

Run `tbd guidelines <name>` to apply any of these guidelines:

| Name | Description |
| --- | --- |
| backward-compatibility-rules | Guidelines for maintaining backward compatibility across code, APIs, file formats, and database schemas |
| cli-agent-skill-patterns | Best practices for building TypeScript CLIs that function as agent skills in Claude Code and other AI coding agents |
| commit-conventions | Conventional Commits format with extensions for agentic workflows |
| convex-limits-best-practices | Comprehensive reference for Convex platform limits, workarounds, and performance best practices |
| convex-rules | Guidelines and best practices for building Convex projects, including database schema design, queries, mutations, and real-world examples |
| error-handling-rules | Rules for handling errors, failures, and exceptional conditions |
| general-coding-rules | Rules for constants, magic numbers, and general coding practices |
| general-comment-rules | Language-agnostic rules for writing clean, maintainable comments |
| general-eng-assistant-rules | Rules for AI assistants acting as senior engineers, including objectivity and communication guidelines |
| general-style-rules | Style guidelines for auto-formatting, emoji usage, and output formatting |
| general-tdd-guidelines | Test-Driven Development methodology and best practices |
| general-testing-rules | Rules for writing minimal, effective tests with maximum coverage |
| golden-testing-guidelines | Guidelines for implementing golden/snapshot testing for complex systems |
| python-cli-patterns | Modern patterns for Python CLI application architecture |
| python-modern-guidelines | Guidelines for modern Python projects using uv, with a few more opinionated practices |
| python-rules | General Python coding rules and best practices |
| sync-troubleshooting | Common issues and solutions for tbd sync and workspace operations |
| typescript-cli-tool-rules | Rules for building CLI tools with Commander.js, picocolors, and TypeScript |
| typescript-code-coverage | Best practices for code coverage in TypeScript with Vitest and v8 provider |
| typescript-monorepo-patterns | Modern patterns for TypeScript monorepo architecture |
| typescript-rules | TypeScript coding rules and best practices |

<!-- END SHORTCUT DIRECTORY -->
<!-- END TBD INTEGRATION -->

<!-- agent-memory:start -->
# Agent memory

This repository uses the central agent memory vault at `/home/dzack/.agent-memory-vault`.

Project memory key: `projects/github.com__dzackgarza__flowmark/index`.

Repository `.agents` and `.hermes` paths are symlinks to the same vault-owned project directory.

Before changing architecture, search both project and global memory:

```bash
agent-memory search --scope both "<task or subsystem>"
```

Record durable repo-specific lessons with:

```bash
agent-memory add --scope project --type decision --title <title> --content <content>
agent-memory add --scope project --type trap --title <title> --content <content>
agent-memory add --scope project --type advice --title <title> --content <content>
agent-memory add --scope project --type context --title <title> --content <content>
agent-memory add --scope project --type reference --title <title> --content <content>
```

Plan work is card-backed. Create and update plan cards with `agent-memory plan add` and `agent-memory plan update`, not `agent-memory add --type plan`.

Use `agent-memory retrieve <key>`, `agent-memory update <key>`, and `agent-memory delete <key>` for memory CRUD.

The vault should be committed at all times. Treat staged or unstaged vault changes as an ephemeral error state. Before normal memory work resumes, load the bundled vault-maintenance skill with `agent-memory maintain skill vault-maintenance` and follow its referenced check, repair, and commit workflows.

Move reusable lessons during maintenance with:

```bash
agent-memory maintain move <key> --to global/advice
```
<!-- agent-memory:end -->

# Review Guidelines

These are additional requirements for reviewing agent work.
They do not replace the reviewer’s normal role, repo-specific standards, or technical judgment.
They provide the failure model that should shape the review.

The task is not merely to review a PR. The task is to decide whether a completion claim is true under the original objective.
The standard is full, correct, provable completion against the original requirements and repo guidelines.
Anything less is incomplete work that must not be treated as a win.

## Failure Model

Agents systematically produce impressive non-completion.
Common patterns are: polished summaries that imply finished work, caveats that quietly narrow the goal, reclassification without proof, delegated discovery presented as resolution, process language that substitutes for evidence, merged PRs treated as completion, passing checks treated as semantic proof, and artifacts that look substantial while leaving required work unowned.

Treat the agent’s summary, PR description, closing comment, issue closure, “goal completed” statement, and self-reported validations as untrusted.
They may be diagnostic pointers, but they are not evidence that the work is complete.
The evidence is the original issue or task, the code diff, tests, source/runtime facts, review comments, and produced artifacts.

## Decisive Invariants

Preserve the original success condition.
Read the original issue or task before accepting any restatement of it.
Keep its quantifiers intact: “all,” “complete,” "full subset," “zero remaining,” and similar terms cannot be quietly narrowed to examples, partial coverage, known blockers, or whatever the PR happened to touch.

Nothing required may disappear silently.
A required work family must be implemented, explicitly falsified, or validly reclassified with evidence that satisfies the issue’s own standard.
Partial implementation is not completion.
Future work is not completion.
Count reduction is not completion.
Resolved review threads are not completion.
Passing checks are not completion.
Substantial-looking work is not completion.
“Better than before” is not completion.

Goal substitution is the main thing to detect.
Ask whether the submitted work solves the original problem or merely produces a narrower artifact: cleaner metadata, a partial subset, a better explanation, a new issue, a renamed scope, a local workaround, or proof that someone should investigate later.

Technically correct administrative artifacts can be goal substitution.
A well-written issue, comment, audit note, scope statement, or enumeration of remaining work may be required, but it does not complete implementation, testing, proof, or downstream cleanup.
If the original task requires execution, the artifact is only useful insofar as it drives that execution; it must not become the stopping point.

Treat self-scoped remaining-work lists as a severe completion-laundering pattern.
When an agent is asked to enumerate remaining work, the domain is the original full completion requirement, not the agent’s intended subset, the PR’s current shape, a closeability criterion, or the work left after deferral and reclassification.
A valid enumeration subtracts only artifact-proven completed work from the original contract.
Deferrals, routed follow-ups, owner changes, and truthful incompletion notes remain unresolved work unless the original task explicitly made that administrative routing the whole deliverable.

If an agent repeats a narrowed enumeration after being corrected, treat that as a hard misalignment signal, not as an innocent wording issue.
The reviewer should identify the original full requirement, the scope the agent substituted, and the required work hidden by that substitution.

Silent reclassification is not resolution.
If the PR says remaining work is out-of-scope, research-owned, stub-owned, plugin-owned, downstream-owned, or future-owned, require evidence from the relevant source/runtime behavior, repo boundary, or original acceptance criteria.
A sentence in the PR description is not enough.

Ownership boundaries matter.
The submitting repo must prove its own claimed behavior and do the blocker forensics required by its own issue.
Do not require a receiving or downstream repo to classify another project’s internal uncertainty unless the original issue explicitly made that part of acceptance.
When an external issue is created, it should be written for that receiving repo, not for a reader who already knows the submitting repo’s context.

## Evidence Expectations

Review tests as evidence, not as decoration.
Valid tests exercise the real production path or semantic requirement.
Be skeptical of helper-only tests, tautologies, assertions of the implementation’s own output, bypasses around the runtime/plugin/stub path, example-only coverage where the issue required full coverage, weakened assertions, and missing invalid-nearby cases where the fix could overgeneralize.

For plugin work, the evidence should usually distinguish valid generic behavior from invalid nearby ordinary Python and should not hard-code a downstream consumer.
For stubs work, the evidence should be source-backed: the upstream surface exists, the stub matches public behavior, no fake API is added, no Any/object opacity escape is introduced, and inherited-method inflation is not used unless source exposes that surface.

Watch for code-level laundering: hard-coded consumer names, support for local research abstractions as if they were external API, fake stubs, broad Any/object escapes, line suppressions, diagnostic filtering, deletion of required data, broad type widening, and any move that makes checks pass by weakening the problem instead of solving it.

## When Acting on Review Feedback

A positive disposition requires a commit.

Do not resolve an accepted review comment until the code/proof remediation is committed and the reply cites the commit.

Never reply “accepted,” “aligned,” “fixed,” “addressed,” or “will address” to a review thread unless the remediation is already committed.
A thread cannot be resolved on intent or future work.

Every substantive review item must receive its visible thread- or surface-local disposition and evidence before resolution.
The canonical field contract and state machine live in [[pr-feedback-triage/SKILL|pr-feedback-triage]]. Do not create top-level disposition ledgers or tracked review-log files.
Migrate legacy ledger-only resolutions by posting the canonical disposition and evidence on each affected thread before treating it as closed.

Review comments are not implementation specs.
The worker must translate accepted feedback into first-principles remediation requirements before assigning implementation.

For each comment:
- Identify the concern.
- Identify the proposed fix.
- Decide whether the concern is true under global + repo policy.
- Decide whether the proposed fix preserves those policies.
- If the concern is true but the fix is wrong, apply a policy-compatible remediation.

## Writing the Review

Write nuanced feedback for an intelligent reader.
Do not force a machine-readable template, a mandatory table, or a simplistic pass/fail label when prose communicates the situation better.
Do make the completion judgment clear: whether the original task can be considered complete, what evidence supports that judgment, and which unresolved requirements block completion if any remain.

Do not foreground effort, progress, good intentions, volume of work, or “substantial” partial implementation when required work remains.
Mention completed pieces only when they are necessary to identify the exact remaining blockers or to prevent redoing already-correct work.
Do not compare incomplete work to “no work done” or “completely fake work”; compare it to the expected standard: the task done correctly, completely, and provably.

When required work remains, lead with the incompleteness and the concrete blockers.
Do not make the reader excavate the missing work from beneath praise, context-setting, or a narrative of what did get done.

Nuance belongs in the evidence and blocker analysis, not in softening the completion standard.
The review should make it easy to finish the work, not easy to feel satisfied with less than the original contract required.
