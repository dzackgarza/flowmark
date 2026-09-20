"""Canonical Pandoc reader dialect for Flowmark's Zettlr authoring surface."""

from __future__ import annotations


PANDOC_FORMAT = (
    "markdown"
    "+fenced_divs"
    "+raw_tex"
    "+tex_math_dollars"
    "+tex_math_single_backslash"
    "+wikilinks_title_after_pipe"
)
"""The exact Pandoc Markdown reader used by the surrounding authoring pipeline.

Pandoc's ``markdown`` defaults already enable citations, pipe/grid tables,
footnotes, bracketed spans, and attributes. ``tex_math_single_backslash`` and
``wikilinks_title_after_pipe`` are not defaults and are load-bearing for this
corpus, so no caller may silently fall back to bare ``markdown``.
"""


__all__ = ("PANDOC_FORMAT",)
