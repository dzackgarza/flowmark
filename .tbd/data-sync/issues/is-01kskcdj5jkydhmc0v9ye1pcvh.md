---
type: is
id: is-01kskcdj5jkydhmc0v9ye1pcvh
title: "Phase B: refactor _extract_atomic_constructs onto iter_atomic_tokens"
kind: task
status: closed
priority: 2
version: 5
spec_path: docs/project/specs/active/plan-2026-05-26-public-inline-api.md
labels: []
dependencies:
  - type: blocks
    target: is-01kskcdjgxdyx2rwyw8nkabwh7
parent_id: is-01kskcc95bk93gn9mz8x57c13z
created_at: 2026-05-27T00:12:44.081Z
updated_at: 2026-05-27T00:58:30.207Z
closed_at: 2026-05-27T00:58:30.207Z
close_reason: Word splitter reimplemented on iter_atomic_words; 324 pytest + 127 golden byte-identical
---
FILE src/flowmark/linewrapping/text_wrapping.py. Reimplement _HtmlMdWordSplitter/_extract_atomic_constructs on flowmark.atomic._iter_atomic_words: words = [w for w,_,_ in _iter_atomic_words(normalize_adjacent_tags(text), ATOMIC_PATTERNS)]. Removes the placeholder substitution dance; single source of truth with iter_atomic_spans. HIGH REGRESSION RISK: wrapping golden corpus must be byte-identical (pytest test_wrapping/test_filling/test_ref_docs + npx tryscript if network allows). If any diff, DO NOT merge the refactor - leave bead open with findings.
