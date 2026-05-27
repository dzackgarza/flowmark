---
type: is
id: is-01kskcdf783b4t174gr6yr2ymf
title: "Phase A: add autolink/bare-URL atomic patterns + extend prose subset"
kind: task
status: closed
priority: 1
version: 4
spec_path: docs/project/specs/active/plan-2026-05-26-public-inline-api.md
labels: []
dependencies:
  - type: blocks
    target: is-01kskcdhdk340wm07vmsmjcfqw
parent_id: is-01kskcc95bk93gn9mz8x57c13z
created_at: 2026-05-27T00:12:41.064Z
updated_at: 2026-05-27T00:54:15.710Z
closed_at: 2026-05-27T00:54:15.710Z
close_reason: Added AUTOLINK + BARE_URL; MARKDOWN_INLINE_PATTERNS extended; subset claim dropped
---
Review #2. FILE src/flowmark/linewrapping/atomic_patterns.py: add AUTOLINK (angle: <scheme:...> and <email>) and BARE_URL (http(s)://... and www...., conservative trailing-punctuation trim so a sentence-ending period is not swallowed) AtomicPatterns. FILE src/flowmark/atomic.py: MARKDOWN_INLINE_PATTERNS = (INLINE_CODE_SPAN, MARKDOWN_LINK, AUTOLINK, BARE_URL). Keep the new patterns OUT of full ATOMIC_PATTERNS for now (wrapping already keeps URLs whole - no internal spaces - and <...> is matched by HTML_OPEN_TAG; adding risks byte-identical golden). SPEC INCONSISTENCY: spec/test claimed MARKDOWN_INLINE_PATTERNS subset of ATOMIC_PATTERNS - drop that assertion; the two sets are purpose-built. Tests: AUTOLINK matches <http://x>, BARE_URL matches bare http/www URL and excludes trailing period.
