from __future__ import annotations

import re
from collections.abc import Generator
from contextlib import contextmanager
from enum import StrEnum
from typing import Any, cast, override

from marko import Markdown, Renderer, block, inline
from marko.ext import footnote
from marko.ext.gfm import elements as gfm_elements
from marko.parser import Parser

from flowmark.formats.flowmark_parser import (
    CustomCitation,
    CustomDefinitionList,
    CustomDisplayMath,
    CustomFencedCode,
    CustomFencedDiv,
    CustomInlineMath,
    CustomLatexEnvironment,
    CustomRawInlineTex,
    CustomWikilink,
    escape_cell_bars,
    flowmark_parser,
)
from flowmark.linewrapping.line_wrappers import (
    line_wrap_by_sentence,
    line_wrap_to_width,
)
from flowmark.linewrapping.protocols import LineWrapper
from flowmark.linewrapping.text_filling import DEFAULT_WRAP_WIDTH
from flowmark.linewrapping.unbreakable import restore_spaces, unbreakable


class ListSpacing(StrEnum):
    """
    Controls how list item spacing is handled during Markdown normalization.

    - preserve: Keep lists tight or loose as authored
    - loose: Convert all lists to loose format (blank lines between items) (default)
    - tight: Convert all lists to tight format where possible
    """

    preserve = "preserve"
    loose = "loose"
    tight = "tight"


def _normalize_title_quotes(title: str) -> str:
    """
    Normalize title quotes.
    """
    escaped = title.strip('"').replace('"', '\\"')
    return f'"{escaped}"'


def _min_fence_length(code_content: str, fence_char: str = "`") -> int:
    """
    Calculate the minimum fence length needed for code content.

    Scans the content for sequences of the fence character at the start of lines
    and returns one more than the longest sequence found (minimum 3).

    Per CommonMark spec, the closing fence must have at least as many fence
    characters as the opening fence. Sequences only matter at the start of
    lines (with up to 3 spaces of indentation).
    """
    max_len = 0
    # Find all sequences of 3+ fence chars at start of line (with optional indent)
    pattern = rf"^[ ]{{0,3}}({re.escape(fence_char)}{{3,}})"
    for match in re.finditer(pattern, code_content, re.MULTILINE):
        fence = match.group(1)
        max_len = max(max_len, len(fence))

    # Need at least one more than the longest found, minimum 3
    return max(3, max_len + 1)


class MarkdownNormalizer(Renderer):
    """
    Render Markdown in normalized form. This is the internal implementation
    which overrides most of `MarkdownRenderer`.

    You likely want to use `normalize_markdown()` instead.

    Based on:
    https://github.com/frostming/marko/blob/master/marko/md_renderer.py
    https://github.com/frostming/marko/blob/master/marko/ext/gfm/renderer.py
    """

    def __init__(
        self, line_wrapper: LineWrapper, list_spacing: ListSpacing = ListSpacing.loose
    ) -> None:
        super().__init__()
        self._prefix: str = (
            ""  # The prefix on the first line, with a bullet, such as `  - `.
        )
        self._second_prefix: str = ""  # The prefix on subsequent lines, such as `    `.
        self._suppress_item_break: bool = True
        self._line_wrapper: LineWrapper = line_wrapper
        self._skip_next_blank_line: bool = False  # Skip blank line following heading
        self._current_inline_text: str = (
            ""  # Track accumulated inline text for escape context
        )
        self._in_heading: bool = False  # Track if we're rendering a heading
        self._list_spacing: ListSpacing = list_spacing
        self._current_list_tight: bool = (
            False  # Whether current list should render tight
        )

    @override
    def __enter__(self) -> MarkdownNormalizer:
        self._prefix = ""
        self._second_prefix = ""
        return super().__enter__()

    @contextmanager
    def container(self, prefix: str, second_prefix: str = "") -> Generator[None]:
        old_prefix, old_second_prefix = self._prefix, self._second_prefix
        self._prefix += prefix
        self._second_prefix += second_prefix
        yield
        self._prefix, self._second_prefix = old_prefix, old_second_prefix

    def render_document(self, element: block.Document) -> str:
        # Inline elements are rendered `unbreakable` so the line wrapper cannot split
        # them; the whole document is wrapped by now.
        rendered: str = self.render_children(element)
        return restore_spaces(rendered)

    def _can_be_tight(self, element: block.List) -> bool:
        """
        Check if a list can be rendered tight.

        A list cannot be tight if any item contains multiple block elements
        (e.g., multiple paragraphs, code blocks, quote blocks) because
        CommonMark requires blank lines to separate these, making the list loose.
        """
        for item in element.children:
            if not isinstance(item, block.ListItem):
                continue
            # If the item has more than one child (multiple block elements), it must be loose
            if len(item.children) > 1:
                return False
        return True

    def render_paragraph(self, element: block.Paragraph) -> str:
        # Reset the skip flag since we're not rendering a blank line
        self._skip_next_blank_line = False
        # After rendering a paragraph, don't suppress the next item break
        # This ensures proper spacing before list items that follow paragraphs
        self._suppress_item_break = False

        # Reset inline text tracking for this paragraph
        self._current_inline_text = ""
        children: Any = self.render_children(element)

        # GFM checkbox support.
        if hasattr(element, "checked"):
            children = f"[{'x' if element.checked else ' '}] {children}"  # pyright: ignore

        if self._second_prefix.rstrip().endswith(">") and "\n" in children:
            first_line, rest = children.split("\n", 1)
            if re.fullmatch(r"\[![^\]]+\](?:[ \t]+.*)?", first_line):
                lines = [f"{self._prefix}{first_line}"]
                if rest:
                    wrapped_rest = self._line_wrapper(
                        rest,
                        self._second_prefix,
                        self._second_prefix,
                    ).rstrip("\n")
                    if wrapped_rest:
                        lines.append(wrapped_rest)
                self._prefix = self._second_prefix
                self._current_inline_text = ""
                return "\n".join(lines) + "\n"

        # Wrap the text.
        wrapped_text = self._line_wrapper(
            children,
            self._prefix,
            self._second_prefix,
        )
        self._prefix = self._second_prefix
        self._current_inline_text = ""
        return wrapped_text + "\n"

    def render_list(self, element: block.List) -> str:
        # Reset the skip flag since we're not rendering a blank line
        self._skip_next_blank_line = False

        # Determine effective tightness based on mode
        if self._list_spacing == ListSpacing.preserve:
            is_tight = element.tight
        elif self._list_spacing == ListSpacing.tight:
            # Only make tight if the list can be tight (no multi-paragraph items)
            is_tight = self._can_be_tight(element)
        else:  # loose
            is_tight = False

        # Save and set the tightness for this list
        old_tight = self._current_list_tight
        self._current_list_tight = is_tight

        result: list[str] = []

        for i, child in enumerate(element.children):
            # Configure the appropriate prefix based on list type
            if element.ordered:
                num = i + element.start
                prefix = f"{num}. "
                subsequent_indent = " " * (len(str(num)) + 2)
            else:
                prefix = f"{element.bullet} "
                subsequent_indent = "  "

            with self.container(prefix, subsequent_indent):
                rendered_item = self.render(child)
                result.append(rendered_item)

        # Restore the previous list's tightness (for nested lists)
        self._current_list_tight = old_tight
        self._prefix = self._second_prefix
        return "".join(result)

    def render_list_item(self, element: block.ListItem) -> str:
        # Explicitly str-typed: render_children (inherited from marko) returns Any,
        # so without this annotation the accumulated result widens to Any.
        result: str = ""
        # For loose lists, add a blank line between items.
        # For tight lists, don't add blank lines.
        if not self._current_list_tight:
            if self._suppress_item_break:
                self._suppress_item_break = False
            else:
                # Add the newline between paragraphs. Normally this would be an empty line but
                # within a quote block it would be the secondary prefix, like `> `.
                result += self._second_prefix.strip() + "\n"

        result += self.render_children(element)

        return result

    def render_quote(self, element: block.Quote) -> str:
        # Reset the skip flag since we're not rendering a blank line
        self._skip_next_blank_line = False

        with self.container("> ", "> "):
            result = self.render_children(element).rstrip("\n")
        self._prefix = self._second_prefix
        # After rendering a quote block, don't suppress the next item break
        # This ensures proper spacing after list items with quote blocks
        self._suppress_item_break = False
        return f"{result}\n"

    def _render_code(
        self, element: block.CodeBlock | block.FencedCode | CustomFencedCode
    ) -> str:
        # Reset the skip flag since we're not rendering a blank line
        self._skip_next_blank_line = False

        # Preserve code content without reformatting.
        code_child = cast(inline.RawText, element.children[0])
        code_content = code_child.children.rstrip("\n")
        lang = element.lang if isinstance(element, block.FencedCode) else ""
        extra = element.extra if isinstance(element, block.FencedCode) else ""
        extra_text = f" {extra}" if extra else ""
        lang_text = f"{lang}{extra_text}" if lang else ""

        # Get fence character and length from CustomFencedCode, or use defaults
        if isinstance(element, CustomFencedCode):
            fence_char = element.fence_char
            original_fence_len = element.fence_len
        else:
            fence_char = "`"
            original_fence_len = 3

        # Calculate minimum fence length needed based on content
        # (must be longer than any fence-like sequences in the content)
        min_fence_len = _min_fence_length(code_content, fence_char)

        # Use the maximum of original and minimum fence lengths
        fence_len = max(original_fence_len, min_fence_len)
        fence = fence_char * fence_len

        lines = [f"{self._prefix}{fence}{lang_text}"]
        # Don't add prefix to empty lines to avoid trailing whitespace.
        # Use rstrip() to preserve structural prefixes like ">" for blockquotes.
        empty_line_prefix = self._second_prefix.rstrip()
        for line in code_content.splitlines():
            if line:
                lines.append(f"{self._second_prefix}{line}")
            else:
                lines.append(empty_line_prefix)
        lines.append(f"{self._second_prefix}{fence}")
        self._prefix = self._second_prefix
        # After rendering a code block, don't suppress the next item break
        # This ensures proper spacing after list items with code blocks
        self._suppress_item_break = False
        return "\n".join(lines) + "\n"

    def render_fenced_code(self, element: block.FencedCode) -> str:
        return self._render_code(element)

    def render_custom_fenced_code(self, element: CustomFencedCode) -> str:
        return self._render_code(element)

    def render_code_block(self, element: block.CodeBlock) -> str:
        # Convert indented code blocks to fenced code blocks.
        return self._render_code(element)

    def render_display_math(self, element: CustomDisplayMath) -> str:
        self._skip_next_blank_line = False
        opener = element.opener
        closer = "\\]" if "[" in opener else "$$"
        code_child = cast(inline.RawText, element.children[0])
        content = code_child.children.rstrip("\n")

        lines = [f"{self._prefix}{opener}"]
        empty_line_prefix = self._second_prefix.rstrip()
        for line in content.splitlines():
            if line:
                lines.append(f"{self._second_prefix}{line}")
            else:
                lines.append(empty_line_prefix)
        lines.append(f"{self._second_prefix}{closer}")
        self._prefix = self._second_prefix
        self._suppress_item_break = False
        return "\n".join(lines) + "\n"

    def render_inline_math(self, element: CustomInlineMath) -> str:
        text = unbreakable(cast(str, element.children))
        self._current_inline_text += text
        return text

    def render_raw_inline_tex(self, element: CustomRawInlineTex) -> str:
        text = unbreakable(cast(str, element.children))
        self._current_inline_text += text
        return text

    def render_citation(self, element: CustomCitation) -> str:
        text = unbreakable(cast(str, element.children))
        self._current_inline_text += text
        return text

    def render_wikilink(self, element: CustomWikilink) -> str:
        text = unbreakable(cast(str, element.children))
        self._current_inline_text += text
        return text

    def render_fenced_div(self, element: CustomFencedDiv) -> str:
        """
        Render the fence lines around a body rendered as ordinary blocks.

        Structurally this is `render_quote` without an indent: the fence is a
        wrapper, so its body gets the enclosing prefixes unchanged rather than a
        `> ` of its own.  Before #20 the body was one `RawText` re-emitted line by
        line, which is why nothing inside a div ever reflowed.
        """
        self._skip_next_blank_line = False
        # Pandoc's canonical spacing is `::: {.foo}`; both spellings carry the
        # same attributes, so normalizing here does not change the parsed AST.
        opener = element.fence
        if element.attrs:
            opener += f" {element.attrs}"

        prefix = self._prefix
        self._prefix = self._second_prefix
        body = self.render_children(element).rstrip("\n")

        lines = [f"{prefix}{opener}"]
        if body:
            lines.append(body)
        lines.append(f"{self._second_prefix}{element.closer}")
        self._prefix = self._second_prefix
        self._suppress_item_break = False
        return "\n".join(lines) + "\n"

    def render_definition_list(self, element: CustomDefinitionList) -> str:
        self._skip_next_blank_line = False
        raw_child = cast(inline.RawText, element.children[0])
        content = raw_child.children.rstrip("\n")

        lines: list[str] = []
        prefix = self._prefix
        empty_line_prefix = self._second_prefix.rstrip()
        for line in content.splitlines():
            lines.append(f"{prefix}{line}" if line.strip() else empty_line_prefix)
            prefix = self._second_prefix
        self._prefix = self._second_prefix
        self._suppress_item_break = False
        return "\n".join(lines) + "\n"

    def render_latex_environment(self, element: CustomLatexEnvironment) -> str:
        self._skip_next_blank_line = False
        env_name = element.env_name
        opener = rf"\begin{{{env_name}}}"
        closer = rf"\end{{{env_name}}}"
        code_child = cast(inline.RawText, element.children[0])
        content = code_child.children.rstrip("\n")

        lines = [f"{self._prefix}{opener}"]
        empty_line_prefix = self._second_prefix.rstrip()
        for line in content.splitlines():
            if line:
                lines.append(f"{self._second_prefix}{line}")
            else:
                lines.append(empty_line_prefix)
        lines.append(f"{self._second_prefix}{closer}")
        self._prefix = self._second_prefix
        self._suppress_item_break = False
        return "\n".join(lines) + "\n"

    def render_html_block(self, element: block.HTMLBlock) -> str:
        result = f"{self._prefix}{element.body}"
        self._prefix = self._second_prefix
        return result

    def render_thematic_break(self, _element: block.ThematicBreak) -> str:
        result = f"{self._prefix}* * *\n"
        self._prefix = self._second_prefix
        return result

    def render_heading(self, element: block.Heading) -> str:
        self._in_heading = True
        self._current_inline_text = ""
        children_content = self.render_children(element)
        self._in_heading = False
        self._current_inline_text = ""
        # If heading ends with hard break, don't add extra newline
        if children_content.endswith("\\"):
            result = f"{self._prefix}{'#' * element.level} {children_content}\n"
            self._prefix = self._second_prefix
            # Don't skip next blank line or suppress item break for hard breaks
            return result
        else:
            # The blank line after the heading must carry the continuation
            # prefix (e.g. "> " inside a blockquote); a bare blank line would
            # end the enclosing block and split it (#12).
            if self._second_prefix.strip():
                blank_line = f"{self._second_prefix}\n"
            else:
                blank_line = "\n"
            result = (
                f"{self._prefix}{'#' * element.level} {children_content}\n{blank_line}"
            )
            self._prefix = self._second_prefix
            # Skip the next blank line since we already added one
            self._skip_next_blank_line = True
            # Suppress the next item break since the heading already added spacing
            self._suppress_item_break = True
            return result

    def render_setext_heading(self, element: block.SetextHeading) -> str:
        return self.render_heading(cast(block.Heading, element))  # pyright: ignore

    def render_blank_line(self, _element: block.BlankLine) -> str:
        if self._skip_next_blank_line:
            self._skip_next_blank_line = False
            return ""
        if self._prefix.strip():
            result = f"{self._prefix}\n"
        else:
            result = "\n"
        self._suppress_item_break = True
        self._prefix = self._second_prefix
        return result

    def render_link_ref_def(self, element: block.LinkRefDef) -> str:
        """Render a standard link reference definition:
        [label]: url "title"
        """
        link_text = element.dest
        if element.title:
            link_text += f" {_normalize_title_quotes(element.title)}"
        result = f"{self._prefix}[{element.label}]: {link_text}\n"
        self._prefix = self._second_prefix
        self._suppress_item_break = True
        return result

    def render_emphasis(self, element: inline.Emphasis) -> str:
        return f"*{self.render_children(element)}*"

    def render_strong_emphasis(self, element: inline.StrongEmphasis) -> str:
        return f"**{self.render_children(element)}**"

    def render_inline_html(self, element: inline.InlineHTML) -> str:
        # Left breakable: HTML tags and comments are template tags to the wrapper,
        # which pairs them by `TEMPLATE_TAG_PATTERNS` and needs their spaces intact.
        return cast(str, element.children)

    def render_link(self, element: inline.Link) -> str:
        return unbreakable(self._render_link(element))

    def _render_link(self, element: inline.Link) -> str:
        link_text = self.render_children(element)
        link_title = _normalize_title_quotes(element.title) if element.title else None
        assert self.root_node
        label = next(
            (
                k
                for k, v in self.root_node.link_ref_defs.items()
                if v == (element.dest, link_title)
            ),
            None,
        )
        if label is not None:
            if label == link_text:
                # Use the collapsed reference form [label][] rather than the
                # shortcut form [label]. A shortcut reference is fragile: it
                # merges with a following "(...)" (becoming an inline link) or
                # "[...]" (becoming a full/collapsed reference), silently
                # changing or dropping links. See issue #45.
                return f"[{label}][]"
            return f"[{link_text}][{label}]"
        title = f" {link_title}" if link_title is not None else ""
        return f"[{link_text}]({element.dest}{title})"

    def render_auto_link(self, element: inline.AutoLink) -> str:
        return unbreakable(f"<{element.dest}>")

    def render_image(self, element: inline.Image) -> str:
        template = "![{}]({}{})"
        title = f" {_normalize_title_quotes(element.title)}" if element.title else ""
        return unbreakable(
            template.format(self.render_children(element), element.dest, title)
        )

    def render_literal(self, element: inline.Literal) -> str:
        """
        Render escaped characters, only preserving the escape when necessary.

        Per CommonMark spec (https://spec.commonmark.org/0.31.2/#backslash-escapes):
        - Any ASCII punctuation character may be backslash-escaped
        - Escapes prevent the character from having its special Markdown meaning
        - See Example 14: "1\\. not a list" - escape needed to prevent list interpretation

        Our approach (smart escaping):
        - Periods: Only escape when needed to prevent list markers (e.g., "1\\." at line start)
          - Remove in headings: "## 1\\." → "## 1." (can't start list in heading)
          - Remove in middle of text: "text 1\\. more" → "text 1. more" (not at line start)
          - Keep at line start: "1\\. not a list" → "1\\. not a list" (prevents list)
        - Other characters (*, #, -, _, etc.): Always preserve escapes
          - These may have meaning in various contexts (emphasis, lists, etc.)
          - Conservative approach: keep escape unless we're certain it's unnecessary

        Related discussions:
        - cmark issue #131: https://github.com/commonmark/cmark/issues/131
          (discusses overly aggressive escaping in renderers)
        """
        # For Literal elements, children is always a string (the escaped character)
        char = cast(str, element.children)

        # Only handle period escapes - leave all other escapes as-is
        # Other punctuation escapes (*, #, -, _, etc.) may be needed for various syntax
        if char != ".":
            self._current_inline_text += f"\\{char}"
            return f"\\{char}"

        # For periods: remove escape in headings
        # Rationale: Can't start a list inside a heading, so period is never special syntax
        if self._in_heading:
            self._current_inline_text += char
            return char

        # For periods: check if this would form a list marker
        # CommonMark requires: 1-9 digits + "." + space to create ordered list
        # Need to escape if:
        # 1. We're at or near the start of a line
        # 2. The accumulated text is just digits (matches list marker pattern: "1.")
        stripped = self._current_inline_text.lstrip()
        if stripped and stripped.isdigit():
            # This is "1\." at line start - preserve escape to prevent list interpretation
            self._current_inline_text += f"\\{char}"
            return f"\\{char}"

        # For all other period cases, the escape is not needed
        self._current_inline_text += char
        return char

    def render_raw_text(self, element: inline.RawText) -> str:
        from marko.ext.pangu import PANGU_RE

        text = re.sub(PANGU_RE, " ", element.children)
        self._current_inline_text += text
        return text

    def render_line_break(self, element: inline.LineBreak) -> str:
        return "\n" if element.soft else "\\\n"

    def render_code_span(self, element: inline.CodeSpan) -> str:
        text = element.children
        if text and (text[0] == "`" or text[-1] == "`"):
            return unbreakable(f"`` {text} ``")
        return unbreakable(f"`{text}`")

    # --- GFM Renderer Methods ---

    def render_footnote_ref(self, element: footnote.FootnoteRef) -> str:
        """Render an inline footnote reference like [^label]."""
        return f"[^{element.label}]"

    def render_footnote_def(self, element: footnote.FootnoteDef) -> str:
        """
        Render a GFM footnote definition, handling content wrapping.
        Note multiline footnotes aren't very well specified but we use
        standard 4-space indentation. See:
        https://github.com/micromark/micromark-extension-gfm-footnote
        """
        # Render label and the rest within an indented container.
        label_part = f"[^{element.label}]: "
        with self.container(label_part, "    "):
            content = self.render_children(element)

        # When the body starts on the line below the label (pandoc allows the
        # label alone on its line), the label's trailing space would be left
        # dangling at end of line.
        content = re.sub(
            r"^(\[\^[^\]]+\]:)[^\n\S]+$", r"\1", content, count=1, flags=re.MULTILINE
        )

        # Set up state for the *next* block element using the restored outer secondary prefix.
        self._prefix = self._second_prefix
        self._suppress_item_break = True  # This definition acts as a block separator.

        # Footnote defs should be separated by extra newlines.
        return content.rstrip("\n") + "\n\n"

    def render_strikethrough(self, element: gfm_elements.Strikethrough) -> str:
        return f"~~{self.render_children(element)}~~"

    def render_table(self, element: gfm_elements.Table) -> str:
        """
        Render a GFM table. Does not do whitespace padding and normalizes
        the delimiters to use three dashes consistently.
        """
        lines: list[str] = []
        head, *body = element.children
        lines.append(self.render(head))

        normalized_delimiters: list[str] = []
        for delimiter in element.delimiters:
            if delimiter.startswith(":") and delimiter.endswith(":"):
                # Center alignment
                normalized_delimiter = ":---:"
            elif delimiter.startswith(":"):
                # Left alignment
                normalized_delimiter = ":---"
            elif delimiter.endswith(":"):
                # Right alignment
                normalized_delimiter = "---:"
            else:
                # No alignment
                normalized_delimiter = "---"
            normalized_delimiters.append(normalized_delimiter)

        lines.append(f"| {' | '.join(normalized_delimiters)} |\n")
        for row in body:
            lines.append(self.render(row))
        return "".join(lines)

    def render_table_row(self, element: gfm_elements.TableRow) -> str:
        """Render a row within a GFM table."""
        return f"| {' | '.join(self.render(cell) for cell in element.children)} |\n"

    def render_table_cell(self, element: gfm_elements.TableCell) -> str:
        """Render a cell within a GFM table row."""
        # render_children (inherited from marko) returns Any; pin it to str.
        rendered: str = self.render_children(element)
        return escape_cell_bars(rendered)

    def render_url(self, element: gfm_elements.Url) -> str:
        """For GFM autolink URLs, just output the URL directly."""
        return unbreakable(element.dest)

    def render_alert(
        self,
        element: block.Quote,  # pyright: ignore[reportUnknownParameterType]
    ) -> str:
        """
        Render a GFM alert/callout block.

        GitHub-flavored Markdown supports alert blocks like:
        > [!NOTE]
        > Content here

        Valid alert types are: NOTE, TIP, IMPORTANT, WARNING, CAUTION

        Note: The element is typed as block.Quote since Alert extends Quote but isn't
        in Marko's type stubs. At runtime, element is gfm_elements.Alert.
        """
        # Reset the skip flag since we're not rendering a blank line
        self._skip_next_blank_line = False

        # First render the alert header. `element` is typed block.Quote because
        # marko's stubs omit the gfm Alert subclass; at runtime it is an Alert with
        # an alert_type attribute, read dynamically to stay within marko's types.
        alert_type: str = getattr(element, "alert_type")
        alert_header = f"> [!{alert_type}]\n"

        with self.container("> ", "> "):
            result = self.render_children(element).rstrip("\n")

        self._prefix = self._second_prefix
        # After rendering an alert block, don't suppress the next item break
        self._suppress_item_break = False
        return f"{alert_header}{result}\n"


DEFAULT_SEMANTIC_LINE_WRAPPER = line_wrap_by_sentence(
    width=DEFAULT_WRAP_WIDTH, is_markdown=True
)
"""
Default line wrapper for semantic line wrapping.
"""

DEFAULT_FIXED_LINE_WRAPPER = line_wrap_to_width(
    width=DEFAULT_WRAP_WIDTH, is_markdown=True
)
"""
Default line wrapper for fixed-width line wrapping.
"""


def flowmark_markdown(
    line_wrapper: LineWrapper = DEFAULT_SEMANTIC_LINE_WRAPPER,
    list_spacing: ListSpacing = ListSpacing.loose,
) -> Markdown:
    """
    Marko Markdown setup for GFM with a few customizations for Flowmark and a new
    renderer that normalizes Markdown according to Flowmark's conventions.
    """

    class CustomRenderer(MarkdownNormalizer):
        def __init__(self) -> None:
            super().__init__(line_wrapper, list_spacing)

    class FlowmarkMarkdown(Markdown):
        """
        Marko Markdown API with Flowmark customizations.
        """

        def __init__(self) -> None:  # pyright: ignore[reportMissingSuperCall]
            pass

        @override
        def _setup_extensions(self) -> None:
            # Using Marko's full extension system is tricky with our customizations so simpler
            # to do this manually.
            custom_parser = flowmark_parser()
            self.parser: Parser = custom_parser
            self.renderer: Renderer = CustomRenderer()

            self._setup_done: bool = True

    return FlowmarkMarkdown()
