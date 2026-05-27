---
type: is
id: is-01kskcdfwb7acajey7r5c9spfe
title: "Phase A: fix iter_inline contract (inline-only vs generic walk)"
kind: task
status: closed
priority: 1
version: 5
spec_path: docs/project/specs/active/plan-2026-05-26-public-inline-api.md
labels: []
dependencies:
  - type: blocks
    target: is-01kskcdg67dmmypqwkjkh71064
  - type: blocks
    target: is-01kskcdgm1nhs4p39s366cnc85
parent_id: is-01kskcc95bk93gn9mz8x57c13z
created_at: 2026-05-27T00:12:41.739Z
updated_at: 2026-05-27T00:54:15.935Z
closed_at: 2026-05-27T00:54:15.935Z
close_reason: Renamed iter_inline -> walk_elements (honest generic walk)
---
Review #4. FILE src/flowmark/ast.py: current iter_inline is a generic descendant DFS mislabeled 'inline' (yields block elements, blank lines, code-block RawText). Rename iter_inline -> walk_elements (honest generic depth-first walk over all descendants; root not yielded). Keep extract_links built on walk_elements (links appear in many block types, so a doc-wide walk is correct; code-block RawText is naturally excluded from results since it is never a Link/Image/AutoLink/Url node). Update __all__ and spec acceptance criteria that referenced iter_inline. No constrained inline-only iterator (YAGNI).
