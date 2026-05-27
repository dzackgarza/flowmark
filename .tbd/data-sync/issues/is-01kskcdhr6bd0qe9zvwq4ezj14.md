---
type: is
id: is-01kskcdhr6bd0qe9zvwq4ezj14
title: "Phase B: split_sentences_with_spans (atomic-aware, offset-preserving)"
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
created_at: 2026-05-27T00:12:43.654Z
updated_at: 2026-05-27T00:58:29.973Z
closed_at: 2026-05-27T00:58:29.973Z
close_reason: split_sentences_with_spans implemented (verbatim, never bisects atomic); tests pass
---
FILE src/flowmark/atomic.py. SentenceSpan(NamedTuple): text,start,end. split_sentences_with_spans(text, min_length=SENTENCE_MIN_LENGTH, heuristic=heuristic_end_of_sentence, patterns=MARKDOWN_INLINE_PATTERNS) -> list[SentenceSpan]. Build words via _iter_atomic_words (NO normalize_adjacent_tags - keep original offsets), accumulate like split_sentences_regex (apply heuristic to each whitespace-delimited word; a link+trailing-punct is ONE word so ').' still triggers; never fires inside an atomic span). Sentence span = text[first_word_start:last_word_end] sliced verbatim from original -> text[start:end]==text. Reuse heuristic_end_of_sentence + SENTENCE_MIN_LENGTH from sentence_split_regex (one-way import; keep split_sentences_regex unchanged).
