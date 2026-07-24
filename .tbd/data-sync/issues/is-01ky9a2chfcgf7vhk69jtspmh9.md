---
type: is
id: is-01ky9a2chfcgf7vhk69jtspmh9
title: Normalize YAML frontmatter separately so pandoc-hostile frontmatter doesn't break formatting
kind: feature
status: closed
priority: 2
version: 2
labels: []
dependencies: []
created_at: 2026-07-24T05:37:45.518Z
updated_at: 2026-07-24T05:55:23.686Z
closed_at: 2026-07-24T05:55:23.685Z
close_reason: "Fixed on main (c252535): verify oracle strips YAML frontmatter before pandoc"
---
## Summary

flowmark routes the entire document — YAML frontmatter included — through pandoc for
both formatting and the meaning-preservation verify. pandoc's YAML metadata reader is
stricter than a general YAML parser, so common, valid-in-practice frontmatter makes
pandoc fail and takes the whole document down with it. flowmark should treat the
frontmatter as its own block: normalize the YAML separately with a YAML-aware tool, and
only hand the markdown body to pandoc.

## Reproduction

A `.md` with ordinary Cursor / agent-rule frontmatter that contains an unquoted glob:

```
---
description: Python Coding Guidelines
globs: *.py, pyproject.toml
alwaysApply: false
---
# Python Coding Guidelines

...body...
```

Running flowmark on it (or `pandoc -f markdown -t json` directly) fails:

```
Error parsing YAML metadata at (line 1, column 1): Unknown alias `a`
```

(older pandoc phrasing: `while scanning an alias: did not find expected alphabetic or
numeric character`.)

## Root cause

`globs: *.py` — a leading `*` in a YAML scalar is an **alias reference** to pandoc's YAML
reader, so `*.py` is parsed as "alias `.py`" and rejected. A general YAML formatter has no
trouble with this (and would quote it), but flowmark never gets that far: `pandoc_verify`
passes the whole document, frontmatter and all, to `pandoc -f markdown -t json`, and the
frontmatter parse error aborts formatting/verification for the entire file.

This is not a rare edge case — unquoted globs (`*.py`, `**/*.ts`), leading-`&`/`*` values,
and other pandoc-hostile-but-common YAML appear throughout Cursor `.mdc`-style and agent
rule frontmatter.

## Requested behavior

- Split the leading YAML frontmatter block from the markdown body before touching pandoc.
- Normalize the frontmatter separately with a YAML-aware formatter (round-trip preserving,
  e.g. ruamel/yq-style), independent of pandoc.
- Format the body — and run the pandoc meaning-preservation verify — on the **body only**,
  so pandoc's strict YAML reader never sees the frontmatter.
- Reassemble frontmatter + formatted body on write.

This makes flowmark robust to documents whose frontmatter is valid YAML but not
pandoc-parseable, and lets the frontmatter get its own (correct) normalization instead of
being an all-or-nothing dependency on pandoc.

## Context

Surfaced while onboarding flowmark to global QC (ai-review-ci): the shared markdown
normalization runs flowmark over all non-test markdown, and vendored agent-rule docs
(`docs/general/agent-rules/*.md`, `.claude/skills/*/SKILL.md`) with `globs: *.py`
frontmatter fail the pandoc parse, blocking the normalization pass.
