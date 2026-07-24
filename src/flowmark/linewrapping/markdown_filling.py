"""
Auto-formatting of Markdown text.

This is similar to what is offered by
[markdownfmt](https://github.com/shurcooL/markdownfmt) but with a few adaptations,
including more aggressive normalization and support for wrapping of lines
semi-semantically (e.g. on sentence boundaries when appropriate).
(See [here](https://github.com/shurcooL/markdownfmt/issues/17) for some old
discussion on why line wrapping this way is convenient.)
"""

from __future__ import annotations

import sys
from textwrap import dedent

from flowmark.formats.flowmark_markdown import ListSpacing, flowmark_markdown
from flowmark.formats.frontmatter import split_frontmatter
from flowmark.linewrapping.line_wrappers import (
    line_wrap_by_sentence,
    line_wrap_to_width,
)
from flowmark.linewrapping.protocols import LineWrapper
from flowmark.linewrapping.tag_handling import preprocess_tag_block_spacing
from flowmark.linewrapping.text_filling import DEFAULT_WRAP_WIDTH
from flowmark.transforms.doc_cleanups import doc_cleanups
from flowmark.transforms.doc_transforms import rewrite_text_across_inlines, rewrite_text_content
from flowmark.typography.ellipses import ellipses as apply_ellipses
from flowmark.typography.smartquotes import smart_quotes


def _strip_blank_edges(text: str) -> str:
    """
    Drop leading and trailing blank lines, leaving the first content line's own
    indentation intact.

    A plain `.strip()` here would take that indentation with it, and four spaces
    are the only thing marking an indented code block, so stripping silently
    demotes a leading code block to a paragraph.
    """
    lines = text.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def fill_markdown(
    markdown_text: str,
    dedent_input: bool = True,
    width: int = DEFAULT_WRAP_WIDTH,
    semantic: bool = False,
    cleanups: bool = False,
    smartquotes: bool = False,
    ellipses: bool = False,
    line_wrapper: LineWrapper | None = None,
    list_spacing: ListSpacing = ListSpacing.loose,
) -> str:
    """
    Normalize and wrap Markdown text filling paragraphs to the full width.

    Wraps lines and adds line breaks within paragraphs and on
    best-guess estimations of sentences, to make diffs more readable.

    With `list_spacing="loose"` (default), all lists have blank lines between items.
    With `list_spacing="preserve"`, list spacing is kept as authored.
    With `list_spacing="tight"`, lists are made tight where possible.

    Optionally also dedents and strips the input, so it can be used
    on docstrings.

    With `semantic` enabled, the line breaks are wrapped approximately
    by sentence boundaries, to make diffs more readable.

    Template tags (Markdoc, Jinja, HTML comments) are always treated atomically
    and never broken across lines.

    Preserves YAML frontmatter (delimited by --- lines) if present at the
    beginning of the document.
    """
    if line_wrapper is None:
        if semantic:
            line_wrapper = line_wrap_by_sentence(width=width, is_markdown=True)
        else:
            line_wrapper = line_wrap_to_width(width=width, is_markdown=True)

    # Extract frontmatter before any processing
    frontmatter, content = split_frontmatter(markdown_text)

    # Only format the content part if there's frontmatter
    if frontmatter:
        markdown_text = content

    if dedent_input:
        markdown_text = _strip_blank_edges(dedent(markdown_text))

    markdown_text = _strip_blank_edges(markdown_text) + "\n"

    # Preprocess: ensure proper blank lines around block content within tags.
    # This must happen before parsing to prevent CommonMark lazy continuation
    # from incorrectly merging tags with lists/tables.
    markdown_text = preprocess_tag_block_spacing(markdown_text)

    # Parse and render.
    marko = flowmark_markdown(line_wrapper, list_spacing)
    document = marko.parse(markdown_text)
    if cleanups:
        # The hyphen join is a heuristic -- #18 says so plainly, and asks for a count
        # rather than silence, because its scope ("digit, lowercase, or inline math",
        # minus the suspension conjunctions) will not be right every time. Saying how
        # many is what lets a reader check them.
        joined = doc_cleanups(document)
        if joined:
            print(
                f"Note: closed up {joined} line break{'s' if joined != 1 else ''} that fell after a hyphen",
                file=sys.stderr,
            )
    if smartquotes:
        rewrite_text_across_inlines(document, smart_quotes)
    if ellipses:
        rewrite_text_content(document, apply_ellipses, coalesce_lines=True)
    result = marko.render(document)

    # End on exactly one newline. Some block renderers append a trailing blank
    # line as a separator from whatever follows; when the block is the document's
    # last, that separator has nothing to separate and shows up as trailing blank
    # lines in the file.
    result = result.rstrip("\n") + "\n"

    # Reattach frontmatter if it was present, with a blank line separator
    if frontmatter:
        result = frontmatter + "\n" + result

    return result
