"""
Public API for Markdown/templating *atomic constructs* — spans of text that must not
be broken in the middle (code spans, links, HTML/Jinja tags and comments).

These are the same patterns flowmark uses internally for line wrapping, exposed here as a
stable, intentional surface so downstream tools can reuse them instead of copying
flowmark internals.

**Heuristic, not a parser.** These patterns identify *unbreakable spans* for wrapping and
tokenization. They are deliberately simpler than a real Markdown parser: ``MARKDOWN_LINK``
does not resolve reference links, handle nested brackets, distinguish images, or honor
escapes. Do **not** use them to enumerate links — for that, parse with
:func:`flowmark.flowmark_markdown` and use :func:`flowmark.ast.extract_links`, which
reflects what Markdown actually treats as a link.
"""

from __future__ import annotations

from flowmark.linewrapping.atomic_patterns import (
    ATOMIC_CONSTRUCT_PATTERN,
    ATOMIC_PATTERNS,
    HTML_CLOSE_TAG,
    HTML_OPEN_TAG,
    INLINE_CODE_SPAN,
    MARKDOWN_LINK,
    PAIRED_HTML_COMMENT,
    PAIRED_JINJA_COMMENT,
    PAIRED_JINJA_TAG,
    PAIRED_JINJA_VAR,
    SINGLE_HTML_COMMENT,
    SINGLE_JINJA_COMMENT,
    SINGLE_JINJA_TAG,
    SINGLE_JINJA_VAR,
    AtomicPattern,
)

# A focused subset for prose: just the Markdown-inline constructs (code spans and links),
# excluding the HTML/Jinja templating patterns in the full wrapping set. Useful for
# sentence splitting and other text analysis that only cares about Markdown inlines.
MARKDOWN_INLINE_PATTERNS: tuple[AtomicPattern, ...] = (
    INLINE_CODE_SPAN,
    MARKDOWN_LINK,
)

__all__ = (
    "AtomicPattern",
    "ATOMIC_PATTERNS",
    "ATOMIC_CONSTRUCT_PATTERN",
    "MARKDOWN_INLINE_PATTERNS",
    "INLINE_CODE_SPAN",
    "MARKDOWN_LINK",
    "SINGLE_JINJA_TAG",
    "PAIRED_JINJA_TAG",
    "SINGLE_JINJA_COMMENT",
    "PAIRED_JINJA_COMMENT",
    "SINGLE_JINJA_VAR",
    "PAIRED_JINJA_VAR",
    "SINGLE_HTML_COMMENT",
    "PAIRED_HTML_COMMENT",
    "HTML_OPEN_TAG",
    "HTML_CLOSE_TAG",
)
