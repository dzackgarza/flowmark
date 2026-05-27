---
type: is
id: is-01kskyww9k8rbexebzyb1xga86
title: "Optional: tag AtomicSpan with the matched pattern name"
kind: feature
status: closed
priority: 3
version: 3
spec_path: docs/project/specs/active/plan-2026-05-26-public-inline-api.md
labels: []
dependencies: []
created_at: 2026-05-27T05:35:40.338Z
updated_at: 2026-05-27T07:14:45.416Z
closed_at: 2026-05-27T07:14:45.416Z
close_reason: Added optional name to AtomicSpan (matched pattern name); test added; wrapping byte-identical
---
Non-blocking ergonomics from PR #47 chopdiff-side review. AtomicSpan carries is_atomic but not WHICH pattern matched, so to attach atomic spans to extract_links results a consumer must re-match link patterns to tell a link span from a code span. Proposal: add optional name: str | None = None to AtomicSpan (matched AtomicPattern.name for atomic spans, None for gaps) and set it in iter_atomic_spans. NamedTuple field with default keeps positional construction compatible. Cheaper to add before release since it changes the public AtomicSpan shape. Stays within the identity/span boundary.
