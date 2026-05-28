---
sandbox: true
env:
  NO_COLOR: "1"
  LC_ALL: C
path:
  - $TRYSCRIPT_GIT_ROOT/.venv/bin
before: |
  cp -r $TRYSCRIPT_TEST_DIR/fixtures/. fixtures/
---

# Verbose, Docs, and Skill Tests

Tests for --skill, --install-skill, and --docs output.
Note: --verbose is Rust-only (not in Python), so this suite focuses on docs/skill
behavior.

## V1: Skill prints SKILL.md content

```console
$ flowmark --skill | sed -n '1,6p'
---
name: flowmark
description: Fast, consistent Markdown auto-formatter — typographic cleanup (smart quotes, ellipses), normalized formatting, and optional clean line wrapping for small, readable git diffs. Use when creating, editing, or normalizing Markdown (.md) files, cleaning up LLM-generated Markdown, or when the user mentions flowmark or formatting Markdown.
allowed-tools: Bash(flowmark:*), Bash(uvx:*), Read, Write
---
# Flowmark - Markdown Auto-Formatter
```

## V2: Docs prints documentation

```console
$ flowmark --docs | grep -Fx "# flowmark"
# flowmark
```

```console
$ flowmark --docs | grep -Fx "## Original Python Flowmark"
## Original Python Flowmark
```

## V3: Install skill creates skill file

```console
$ flowmark --install-skill --agent-base tmpagent >/dev/null && test -f tmpagent/skills/flowmark/SKILL.md && echo "skill installed"
skill installed
```

## V4: Install skill creates nested directories

```console
$ flowmark --install-skill --agent-base deep/nested/path >/dev/null && test -f deep/nested/path/skills/flowmark/SKILL.md && echo "nested dirs created"
nested dirs created
```

## V5: Skill output contains required frontmatter

```console
$ flowmark --skill | grep -F -- "flowmark --docs" | sed 's/^> //'
**Full documentation: run `flowmark --docs` for all options and usage.**
```

## V6: Install skill project-local default writes all three surfaces

```console
$ mkdir v6 && cd v6 && flowmark --install-skill >/dev/null && test -f .agents/skills/flowmark/SKILL.md && test -f .claude/skills/flowmark/SKILL.md && test -f AGENTS.md && echo "all surfaces installed"
all surfaces installed
```

## V7: Install skill --claude-only skips the portable surface

```console
$ mkdir v7 && cd v7 && flowmark --install-skill --claude >/dev/null && test -f .claude/skills/flowmark/SKILL.md && test ! -e .agents && test ! -e AGENTS.md && echo "claude-only"
claude-only
```

## V7b: Install skill --codex writes only the portable surface and AGENTS.md

```console
$ mkdir v7b && cd v7b && flowmark --install-skill --codex >/dev/null && test -f .agents/skills/flowmark/SKILL.md && test -f AGENTS.md && test ! -e .claude && echo "codex-only"
codex-only
```

## V8: Install skill --all writes every surface

```console
$ mkdir v8 && cd v8 && flowmark --install-skill --all >/dev/null && test -f .agents/skills/flowmark/SKILL.md && test -f .claude/skills/flowmark/SKILL.md && test -f AGENTS.md && echo "all surfaces installed"
all surfaces installed
```

## V9: Install skill --skip-claude skips only the Claude mirror

```console
$ mkdir v9 && cd v9 && flowmark --install-skill --skip-claude >/dev/null && test -f .agents/skills/flowmark/SKILL.md && test -f AGENTS.md && test ! -e .claude && echo "skipped claude"
skipped claude
```

## V10: Install skill --skip-codex skips only the portable surface

```console
$ mkdir v10 && cd v10 && flowmark --install-skill --skip-codex >/dev/null && test -f .claude/skills/flowmark/SKILL.md && test ! -e .agents && test ! -e AGENTS.md && echo "skipped codex"
skipped codex
```

## V11: Install skill with every target skipped exits non-zero

```console (exit-code=2)
$ mkdir v11 && cd v11 && flowmark --install-skill --skip-claude --skip-codex 2>&1 1>/dev/null | grep -o "at least one target surface"
at least one target surface
```
