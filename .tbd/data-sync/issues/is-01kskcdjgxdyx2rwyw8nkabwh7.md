---
type: is
id: is-01kskcdjgxdyx2rwyw8nkabwh7
title: "Phase C (gated): evaluate atomic-aware splitting as default"
kind: task
status: closed
priority: 3
version: 4
spec_path: docs/project/specs/active/plan-2026-05-26-public-inline-api.md
labels: []
dependencies: []
parent_id: is-01kskcc95bk93gn9mz8x57c13z
created_at: 2026-05-27T00:12:44.444Z
updated_at: 2026-05-27T03:55:45.813Z
closed_at: 2026-05-27T03:55:45.813Z
close_reason: Evaluated equal-or-better (1 doc, 0 regressions, fixes link-bisection); flipped default to atomic-aware with sign-off; goldens regenerated
---
FILE src/flowmark/linewrapping/line_wrappers.py. Provide opt-in atomic-aware SentenceSplitter (split_sentences_with_spans -> [sp.text]) and evaluate routing line_wrap_by_sentence default through it: diff golden corpus. GATED: adopt as default ONLY if byte-identical/equal-or-better; else keep opt-in and document findings. Conservative default: leave unchanged unless safe.
