---
type: is
id: is-01kskcdg67dmmypqwkjkh71064
title: "Phase A: fix extract_links Url/AutoLink branch + span-recovery docs"
kind: task
status: closed
priority: 2
version: 4
spec_path: docs/project/specs/active/plan-2026-05-26-public-inline-api.md
labels: []
dependencies:
  - type: blocks
    target: is-01kskcdgm1nhs4p39s366cnc85
parent_id: is-01kskcc95bk93gn9mz8x57c13z
created_at: 2026-05-27T00:12:42.054Z
updated_at: 2026-05-27T00:54:16.159Z
closed_at: 2026-05-27T00:54:16.158Z
close_reason: Dropped dead Url branch (Url subclasses AutoLink); softened span-recovery docs
---
Review #6. FILE src/flowmark/ast.py extract_links: confirmed gfm_elements.Url IS a subclass of inline.AutoLink, so the separate Url branch is dead under current ordering. Drop the Url branch; the inline.AutoLink branch already covers bare GFM URLs (Url is-a AutoLink). Update extract_links docstring to reflect that AutoLink covers both <url> autolinks and GFM bare URLs. Also soften Link docstring: span recovery is a source-mapping problem (duplicate link text, reference links, escaped text, nested inline markup), NOT just 'locate the link text'.
