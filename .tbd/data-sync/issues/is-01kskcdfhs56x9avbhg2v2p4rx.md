---
type: is
id: is-01kskcdfhs56x9avbhg2v2p4rx
title: "Phase A: define a clean public pattern type/factory"
kind: task
status: closed
priority: 1
version: 6
spec_path: docs/project/specs/active/plan-2026-05-26-public-inline-api.md
labels: []
dependencies:
  - type: blocks
    target: is-01kskcdf783b4t174gr6yr2ymf
  - type: blocks
    target: is-01kskcdhdk340wm07vmsmjcfqw
parent_id: is-01kskcc95bk93gn9mz8x57c13z
created_at: 2026-05-27T00:12:41.400Z
updated_at: 2026-05-27T00:54:15.477Z
closed_at: 2026-05-27T00:54:15.477Z
close_reason: AtomicPattern delimiter fields now default to ''; usable as public type
---
Review #3. FILE src/flowmark/linewrapping/atomic_patterns.py: give AtomicPattern's four delimiter fields (open_delim, close_delim, open_re, close_re) defaults of '' (frozen dataclass; name+pattern stay required). tag_handling.py sets them explicitly so nothing breaks; public consumers then construct AtomicPattern(name=..., pattern=r'...'). No parallel type/factory needed. Re-export AtomicPattern from flowmark.atomic (already done). Test: AtomicPattern(name='x', pattern='y') works with delim defaults.
