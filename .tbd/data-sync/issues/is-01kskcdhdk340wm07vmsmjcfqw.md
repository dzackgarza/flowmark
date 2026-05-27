---
type: is
id: is-01kskcdhdk340wm07vmsmjcfqw
title: "Phase B: iter_atomic_spans (offset-preserving, selectable patterns)"
kind: task
status: closed
priority: 2
version: 7
spec_path: docs/project/specs/active/plan-2026-05-26-public-inline-api.md
labels: []
dependencies:
  - type: blocks
    target: is-01kskcdhr6bd0qe9zvwq4ezj14
  - type: blocks
    target: is-01kskcdj5jkydhmc0v9ye1pcvh
parent_id: is-01kskcc95bk93gn9mz8x57c13z
created_at: 2026-05-27T00:12:43.315Z
updated_at: 2026-05-27T00:58:29.703Z
closed_at: 2026-05-27T00:58:29.703Z
close_reason: iter_atomic_spans + iter_atomic_words implemented in atomic_patterns; round-trip tests pass
---
FILE src/flowmark/atomic.py. AtomicSpan(NamedTuple): text,start,end,is_atomic. iter_atomic_spans(text, patterns=ATOMIC_PATTERNS) -> Iterator[AtomicSpan]: build combined alternation regex from patterns (re.DOTALL; cache per patterns tuple via functools.cache on a tuple key), re.finditer, yield non-atomic gap spans between matches + atomic match spans, covering text exactly. Round-trip: ''.join(sp.text)==text and text[sp.start:sp.end]==sp.text. Shared internal helper _iter_atomic_words(text, patterns) -> (word,start,end) glues atomic spans to adjacent non-space chars and keeps internal spaces (matches get_html_md_word_splitter: 'foo[a](b)bar' one word, '[click here](u)' one word) - used by fm-812a and fm-sa7r.
