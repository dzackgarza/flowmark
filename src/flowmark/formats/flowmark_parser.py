"""
Flowmark's Markdown parser: marko with GFM, footnotes, and the pandoc constructs
flowmark reads the way pandoc's `markdown` does (math, raw TeX, fenced divs,
definition lists, LaTeX environments).

This is the reading half of `flowmark.formats.flowmark_markdown`, split out so that
code which only needs to parse -- the tag handling inside the line wrappers --
does not depend on the renderer, which depends on the line wrappers.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator, Sequence
from typing import NamedTuple, cast, override

from marko import block, inline
from marko.block import HTMLBlock
from marko.element import Element
from marko.ext import footnote
from marko.ext.gfm import GFM
from marko.ext.gfm import elements as gfm_elements
from marko.helpers import partition_by_spaces
from marko.parser import Parser
from marko.source import Source

from flowmark.linewrapping.atomic_patterns import DOLLAR_MATH, INLINE_CODE_SPAN
from flowmark.linewrapping.unbreakable import refuse_if_present


def _next_line(source: Source) -> str | None:
    """
    marko types `Source.next_line()` as non-Optional, but it returns None at
    end of input, so callers' defensive `is None` checks are real, not dead code.
    """
    return cast("str | None", source.next_line())


class CustomHTMLBlock(HTMLBlock):
    """
    An HTML comment that starts a block and ends a line.

    Pandoc's `markdown` reads such a comment as one `RawBlock`, its line breaks
    included, so it is kept verbatim rather than reflowed. This is CommonMark's HTML
    block type 2, narrowed to where pandoc agrees: CommonMark also takes any text
    after the `-->` into the block, but pandoc reads that text as a paragraph, so a
    comment followed by text on its closing line stays paragraph text here.

    The other CommonMark HTML block types are not read: a block started by an HTML
    tag runs to the next blank line in CommonMark, while pandoc goes on reading
    Markdown inside it (`markdown_in_html_blocks`); see also
    https://github.com/frostming/marko/issues/202.
    """

    @override
    @classmethod
    def match(cls, source: Source) -> int | bool:
        if not source.expect_re(r" {,3}<!--(?:(?!-->)[\s\S])*-->[ \t]*(?:\n|$)"):
            return False
        return super().match(source)

    @override
    @classmethod
    def get_type(cls, snake_case: bool = False) -> str:
        return "html_block" if snake_case else "HTMLBlock"


class ExtendedParseInfo(NamedTuple):
    """Extended parse info that includes fence character and length."""

    prefix: str
    leading: str
    lang: str
    extra: str
    fence_char: str
    fence_len: int


def _is_unicode_punctuation(c: str) -> bool:
    """Check if a character is Unicode punctuation per GFM spec.

    Includes characters in Unicode categories Pc, Pd, Pe, Pf, Pi, Po, Ps,
    plus ASCII symbols (U+0021-U+002F, U+003A-U+0040, U+005B-U+0060, U+007B-U+007E).
    """
    return unicodedata.category(c).startswith("P") or (
        "\u0021" <= c <= "\u002f"
        or "\u003a" <= c <= "\u0040"
        or "\u005b" <= c <= "\u0060"
        or "\u007b" <= c <= "\u007e"
    )


class CustomStrikethrough(gfm_elements.Strikethrough):
    """
    Fixed Strikethrough that implements GFM flanking delimiter rules.

    Marko's default pattern `(?<!~)(~|~~)([^~]+)\\1(?!~)` does not enforce
    that the closing tilde must be right-flanking (not preceded by whitespace)
    or that the opening tilde must be left-flanking (not followed by whitespace).
    This causes `~60 seconds, ~130 words` to be incorrectly parsed as
    strikethrough, since the space before the second `~` makes it left-flanking
    only, not right-flanking, so it cannot close the span.

    The fixed pattern adds:
    - `(?!\\s)` after the opening delimiter (left-flanking: not followed by whitespace)
    - `(?<!\\s)` before the closing delimiter (right-flanking: not preceded by whitespace)
    - Non-greedy `+?` for correct minimal matching

    The `find` method adds full GFM punctuation flanking checks that can't be
    expressed in a simple regex. Per the GFM spec, a delimiter preceded by
    punctuation is only right-flanking if followed by whitespace, punctuation,
    or end of string. Without this, `~100 (~200)` gets incorrectly parsed as
    strikethrough because `(~` matches as a closing delimiter.

    Single tildes are never strikethrough here, although GFM allows them: this
    fork targets pandoc markdown, where `~x~` is a *subscript* (`H~2~O`).
    Parsing it as strikethrough re-emits doubled tildes, turning the subscript
    into a strikeout (#11).  Only `~~` opens a span; single-tilde text passes
    through untouched, which preserves subscripts byte-for-byte.
    """

    pattern: re.Pattern[str] = re.compile(r"(?<!~)(~~)(?!\s)([^~]+?)(?<!\s)\1(?!~)")
    priority: int = 5
    parse_children: bool = True
    parse_group: int = 2

    @override
    @classmethod
    def find(cls, text: str, *, source: Source) -> Iterator[re.Match[str]]:
        """Filter matches by full GFM flanking delimiter rules.

        The regex handles whitespace flanking checks. This method adds
        punctuation flanking checks per GFM spec:

        - Left-flanking: not followed by punctuation, OR followed by punctuation
          AND preceded by whitespace/punctuation/start of string
        - Right-flanking: not preceded by punctuation, OR preceded by punctuation
          AND followed by whitespace/punctuation/end of string
        """
        for match in cls.pattern.finditer(text):
            delim_len = len(match.group(1))

            # Opening delimiter positions
            open_start = match.start()
            open_end = open_start + delim_len

            # Closing delimiter positions
            close_end = match.end()
            close_start = close_end - delim_len

            # Left-flanking check for opening delimiter (punctuation rule)
            char_after_open = text[open_end] if open_end < len(text) else None
            if char_after_open and _is_unicode_punctuation(char_after_open):
                # Followed by punctuation — only left-flanking if preceded by
                # whitespace, punctuation, or start of string
                char_before_open = text[open_start - 1] if open_start > 0 else None
                if char_before_open is not None and not (
                    char_before_open.isspace()
                    or _is_unicode_punctuation(char_before_open)
                ):
                    continue

            # Right-flanking check for closing delimiter (punctuation rule)
            char_before_close = text[close_start - 1] if close_start > 0 else None
            if char_before_close and _is_unicode_punctuation(char_before_close):
                # Preceded by punctuation — only right-flanking if followed by
                # whitespace, punctuation, or end of string
                char_after_close = text[close_end] if close_end < len(text) else None
                if char_after_close is not None and not (
                    char_after_close.isspace()
                    or _is_unicode_punctuation(char_after_close)
                ):
                    continue

            yield match

    @override
    @classmethod
    def get_type(cls, snake_case: bool = False) -> str:
        # Ensure renderer dispatch uses "strikethrough" not "custom_strikethrough".
        return "strikethrough" if snake_case else "Strikethrough"


# One token of a pipe-table row: a code span, `$` math, a backslash escape, or a
# cell-separating bar. Alternation order matters only for the code span, whose
# backreference needs group 1.
_PIPE_ROW_TOKEN = re.compile(
    rf"{INLINE_CODE_SPAN.pattern}|{DOLLAR_MATH}|\\.|(?P<bar>\|)"
)


def split_pipe_table_row(line: str) -> list[str]:
    """
    The cells of a pipe-table row, split where pandoc splits them.

    Pandoc's `markdown` reader parses a cell's inlines before it looks for the
    `|` that ends the cell (`pipeTableCell` in `Text.Pandoc.Readers.Markdown`), so
    a bar inside a code span or `$...$` math is cell content. GFM's rule, which
    marko implements, splits on every unescaped bar instead.
    """
    stripped = line.strip()
    bars = [m.start() for m in _PIPE_ROW_TOKEN.finditer(stripped) if m.group("bar")]
    edges = [-1, *bars, len(stripped)]
    cells = [stripped[a + 1 : b].strip() for a, b in zip(edges, edges[1:])]
    if cells and stripped.startswith("|"):
        cells.pop(0)
    if cells and not cells[-1] and stripped.endswith("|"):
        cells.pop()
    return cells


def escape_cell_bars(text: str) -> str:
    """Escape each bar in rendered cell `text` that pandoc would read as a separator."""
    return _PIPE_ROW_TOKEN.sub(lambda m: "\\|" if m.group("bar") else m.group(0), text)


def _unescape_cell_bars(text: str) -> str:
    """
    Turn each escaped bar outside a code span or math into a plain `|`.

    Inside a span pandoc keeps `\\|` as written: it is TeX's norm `\\|x\\|` or code.
    """
    return _PIPE_ROW_TOKEN.sub(
        lambda m: "|" if m.group(0) == "\\|" else m.group(0), text
    )


class CustomTableCell(gfm_elements.TableCell):
    """A GFM table cell that unescapes `\\|` only where pandoc does."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        # marko's `TableCell.__init__` replaces every `\|`, spans included.
        self.inline_body: str = _unescape_cell_bars(text.strip())

    @override
    @classmethod
    def get_type(cls, snake_case: bool = False) -> str:
        return "table_cell" if snake_case else "TableCell"


class CustomTableRow(gfm_elements.TableRow):
    """A GFM table row whose cells are split by `split_pipe_table_row`."""

    @override
    @classmethod
    def match(cls, source: Source) -> bool:
        # marko's `TableRow.match` with pandoc's row rules
        # (marko/ext/gfm/elements.py, marko 2.2.2): a row has a `|` outside code
        # and math, and a delimiter cell is exactly `:?-+:?`. marko accepted a bar
        # anywhere and matched the delimiter as a prefix, so a paragraph with
        # `$|a|$` above a `- item` line became a table.
        line = _next_line(source)
        if not line or not re.match(r" {,3}\S", line):
            return False
        if not any(m.group("bar") for m in _PIPE_ROW_TOKEN.finditer(line.strip())):
            return False
        cells = split_pipe_table_row(line)
        if not cells:
            return False
        source.context.cells = cells
        source.context.is_delimiter = all(
            cls.delimiter.fullmatch(cell) for cell in cells
        )
        return True

    @override
    @classmethod
    def parse(cls, source: Source) -> CustomTableRow:
        # marko's `TableRow.parse` building `CustomTableCell`s
        # (marko/ext/gfm/elements.py, marko 2.2.2). A row keeps cells past the
        # header's width: pandoc drops them from its reading, so the gate cannot
        # see their text, and writing them back is the only thing preserving it.
        source.consume()
        table = cast("gfm_elements.Table", source.state)
        texts: list[str] = source.context.cells[:]
        texts.extend("" for _ in range(table.num_of_cols - len(texts)))
        cells: list[gfm_elements.TableCell] = [CustomTableCell(t) for t in texts]
        for head, cell in zip(table.head.children, cells):
            cell.align = cast("gfm_elements.TableCell", head).align
        return cls(cells)

    @override
    @classmethod
    def get_type(cls, snake_case: bool = False) -> str:
        return "table_row" if snake_case else "TableRow"


class CustomTable(gfm_elements.Table):
    """
    A GFM table built from `CustomTableRow` and `CustomTableCell`.

    `match` and `parse` are marko's `Table.match` and `Table.parse`
    (marko/ext/gfm/elements.py, marko 2.2.2) with the row and cell classes
    replaced: marko names them directly rather than looking them up in the parser.
    """

    @override
    @classmethod
    def match(cls, source: Source) -> bool:
        source.anchor()
        if not CustomTableRow.match(source) or source.context.is_delimiter:
            return False
        # Re-reading the head row sets `source.match` to it; the row just matched
        # is a non-empty line, so the read succeeds.
        _next_line(source)
        source.pos = cast("re.Match[str]", source.match).end()
        head = CustomTableRow([CustomTableCell(cell) for cell in source.context.cells])
        if (
            not CustomTableRow.match(source)
            or not source.context.is_delimiter
            or len(source.context.cells) != len(head.children)
        ):
            source.reset()
            return False
        source.context.table_info = {
            "children": [head],
            "delimiters": source.context.cells,
        }
        source.consume()
        return True

    @override
    @classmethod
    def parse(cls, source: Source) -> CustomTable:
        table = cls(**source.context.table_info)
        rows = cast("list[gfm_elements.TableRow]", table.children)
        # marko's `Parser._build_block_element_list`, through public attributes.
        interrupters = sorted(
            (
                element
                for element in source.parser.block_elements.values()
                if not element.virtual
                and not issubclass(element, (gfm_elements.Table, block.Paragraph))
            ),
            key=lambda element: element.priority,
            reverse=True,
        )
        with source.under_state(table):
            for delimiter, head_cell in zip(table.delimiters, table.head.children):
                th = cast("gfm_elements.TableCell", head_cell)
                stripped = delimiter.strip()
                th.header = True
                if stripped[0] == ":" and stripped[-1] == ":":
                    th.align = "center"
                elif stripped[0] == ":":
                    th.align = "left"
                elif stripped[-1] == ":":
                    th.align = "right"
            while not source.exhausted:
                if any(element.match(source) for element in interrupters):
                    break
                if not CustomTableRow.match(source):
                    break
                rows.append(CustomTableRow.parse(source))
        return table

    @override
    @classmethod
    def get_type(cls, snake_case: bool = False) -> str:
        return "table" if snake_case else "Table"


class CustomFencedCode(block.FencedCode):
    """
    Extended FencedCode that preserves the fence character and length.

    This allows us to preserve the original fence style (backticks vs tildes)
    and length (3+ characters) when normalizing markdown.
    """

    lang: str
    extra: str
    children: list[inline.RawText]
    fence_char: str = "`"
    fence_len: int = 3

    def __init__(  # pyright: ignore[reportMissingSuperCall]
        self, match: tuple[str, str, str, str, int]
    ) -> None:
        # We intentionally don't call super().__init__ because we need a different
        # tuple format that includes fence_char and fence_len
        self.lang = inline.Literal.strip_backslash(match[0])
        self.extra = match[1]
        self.children = [inline.RawText(match[2], False)]
        self.fence_char = match[3]
        self.fence_len = match[4]

    @override
    @classmethod
    def match(cls, source: Source) -> re.Match[str] | None:
        m = source.expect_re(cls.pattern)
        if not m:
            return None
        prefix, leading, info = m.groups()
        if leading[0] == "`" and "`" in info:
            return None
        lang, _, extra = partition_by_spaces(info)
        # Store extended info including fence_char and fence_len
        fence_char = leading[0]
        fence_len = len(leading)
        source.context.code_info = ExtendedParseInfo(
            prefix, leading, lang, extra, fence_char, fence_len
        )
        return m

    @override
    @classmethod
    def parse(  # pyright: ignore[reportIncompatibleMethodOverride]
        cls, source: Source
    ) -> tuple[str, str, str, str, int]:
        # We intentionally return a different tuple format than the parent class
        # to include fence_char and fence_len
        source.next_line()
        source.consume()
        lines: list[str] = []
        parse_info: ExtendedParseInfo = source.context.code_info
        while not source.exhausted:
            line = _next_line(source)
            if line is None:
                break
            source.consume()
            m = re.match(r" {,3}(~+|`+)[^\n\S]*$", line, flags=re.M)
            if m and parse_info.leading in m.group(1):
                break

            prefix_len = source.match_prefix(parse_info.prefix, line)
            if prefix_len >= 0:
                line = line[prefix_len:]
            else:
                line = line.lstrip()
            lines.append(line)
        return (
            parse_info.lang,
            parse_info.extra,
            "".join(lines),
            parse_info.fence_char,
            parse_info.fence_len,
        )


class CustomDisplayMath(block.BlockElement):
    """
    Display math block: ``\\[...\\]`` or ``$$...$$``.

    Content between delimiters is preserved verbatim. Parsed as a block-level
    element so it never passes through paragraph line-wrapping (which would join
    the delimiters and content onto one line) or hard-break normalization (which
    would corrupt ``\\[`` followed by two trailing spaces into ``\\[\\``).
    """

    priority: int = 7
    parse_children: bool = True
    pattern: re.Pattern[str] = re.compile(r"( {,3})(\\\[|\$\$)\s*$", re.MULTILINE)

    children: Sequence[Element]
    opener: str
    prefix: str

    def __init__(self, match: re.Match[str]) -> None:
        self.opener = match[0]
        self.prefix = match[1]
        self.children = [inline.RawText(match[2], False)]

    @override
    @classmethod
    def match(cls, source: Source) -> re.Match[str] | None:
        m = source.expect_re(cls.pattern)
        if not m:
            return None
        prefix, opener = m.groups()
        source.context.math_info = (prefix, opener)
        return m

    @override
    @classmethod
    def parse(cls, source: Source) -> tuple[str, str, str]:
        prefix, opener = source.context.math_info
        source.next_line()
        source.consume()

        closer = "\\]" if "[" in opener else "$$"

        lines: list[str] = []
        while not source.exhausted:
            line = _next_line(source)
            if line is None:
                break
            source.consume()

            # Check if the line ends with the closer (after stripping
            # trailing whitespace).  The closer can appear at line-start
            # (like a code fence) or after content on the same line
            # (like `\\frac{1}{2},\\]`).
            stripped = line.rstrip()
            if stripped.endswith(closer):
                before = stripped[: -len(closer)].rstrip()
                if before:
                    # Content before the closer on the same line:
                    # append to the previous content line, not as a
                    # separate line (avoids splitting `,\\]` into
                    # `,\\n\\]`).
                    if lines:
                        lines[-1] = lines[-1].rstrip("\n") + before + "\n"
                    else:
                        lines.append(before + "\n")
                break

            prefix_len = source.match_prefix(prefix, line)
            if prefix_len >= 0:
                line = line[prefix_len:]
            else:
                line = line.lstrip()
            lines.append(line)

        return (opener, prefix, "".join(lines))

    @override
    @classmethod
    def get_type(cls, snake_case: bool = False) -> str:
        return "display_math" if snake_case else "DisplayMath"


class CustomInlineMath(inline.InlineElement):
    """
    Inline math span: ``$...$`` or ``$$...$$`` inside a paragraph.

    Content between delimiters is preserved verbatim.  Parsed as a custom inline
    element so underscores and asterisks inside LaTeX are not interpreted as
    Markdown emphasis and then re-rendered as ``*`` markers.  What counts as math
    is pandoc's rule, `DOLLAR_MATH`.
    """

    priority: int = 7
    parse_children: bool = False
    # The whole ``$...$`` span is preserved verbatim, delimiters included, so
    # marko's own ``__init__`` storing ``match.group(0)`` in ``children`` is
    # exactly what rendering needs.
    parse_group: int = 0
    # The union annotation mirrors marko's `InlineElement.pattern`; attribute
    # overrides may not narrow it.
    pattern: re.Pattern[str] | str = re.compile(DOLLAR_MATH)

    @override
    @classmethod
    def get_type(cls, snake_case: bool = False) -> str:
        return "inline_math" if snake_case else "InlineMath"


class CustomRawInlineTex(inline.InlineElement):
    """
    A raw LaTeX command with brace arguments, e.g. ``\\overline{ \\mathcal{M}_{1} }``.

    Pandoc reads such a run as a raw TeX inline and passes it through verbatim, so
    its underscores are LaTeX subscripts, not Markdown emphasis. Parsed here as a
    custom inline element (``parse_children = False``) for the same reason as
    `CustomInlineMath`: otherwise two underscores in separate commands pair up as
    an emphasis span and get re-rendered with ``*``, producing invalid LaTeX.

    Only commands carrying at least one brace group are matched. A bare ``\\alpha``
    has no braces to hide an underscore in, and matching escapes like ``\\_`` or the
    ``\\[``/``\\(`` math delimiters would break their own handling -- the leading
    ``[a-zA-Z]+`` excludes all of those.

    Brace arguments may nest three deep (``\\overline{ \\mathcal{M}_{1} }`` uses two),
    which covers ordinary mathematical prose; `re` cannot match arbitrary nesting, so
    the depth is fixed by the pattern below and a deeper command is left unmatched.
    """

    priority: int = 7
    parse_children: bool = False
    # The whole match is the construct; there is no inner group to descend into.
    parse_group: int = 0
    # The union annotation mirrors marko's `InlineElement.pattern`; attribute
    # overrides may not narrow it.
    pattern: re.Pattern[str] | str = re.compile(
        r"\\[a-zA-Z]+(?:\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\})+"
    )

    @override
    @classmethod
    def get_type(cls, snake_case: bool = False) -> str:
        return "raw_inline_tex" if snake_case else "RawInlineTex"


class CustomFencedDiv(block.BlockElement):
    """
    Pandoc fenced div: ``::: {.attrs}`` ... ``:::``.

    The opening fence is three or more colons, and pandoc treats the entire
    remainder of that line as the div's attribute specification -- either a
    braced block (``{#id .class key="val"}``) or a bare class word
    (``::: proof``, shorthand for ``::: {.proof}``).  There is no "trailing
    content on the same line": pandoc rejects ``::: {.foo} text`` as a div
    outright, so the attribute spec is captured verbatim and never re-emitted
    as body content.  The closing fence may be shorter than the opening one and
    is preserved as written.

    The **body is ordinary markdown** and is parsed as blocks, so it reflows like
    any other content (#20).  The fence is a semantic wrapper, not a content mode:
    pandoc reads ``::: {.problem}\\ntext\\n:::`` as ``Div [Para [...]]`` with
    normal inlines, so there is nothing in there to protect.  This is what
    separates a div from its verbatim-capture neighbours -- ``DisplayMath``,
    ``RawInlineTex``, ``LatexEnvironment`` -- whose bodies are genuinely not
    markdown.

    Finding the body still needs the scan below rather than marko's own block
    loop: a nested div's closer must not terminate this one, and a colon run
    inside a fenced code block is literal text rather than a fence.

    https://pandoc.org/MANUAL.html#divs-and-spans
    """

    priority: int = 7
    parse_children: bool = True
    # Group 1: whitespace prefix, Group 2: the colon fence, Group 3: attribute spec.
    # The attribute spec is taken verbatim rather than parsed: a braced block may
    # contain a `}` inside a quoted value (`title="{[@Cite, Thm. 1]}"`), which no
    # non-recursive brace pattern can delimit correctly, and pandoc gives the rest
    # of the line no other meaning anyway. [^\n\S]* matches horizontal whitespace
    # only (same pattern used by CustomFencedCode for its info line) so the opening
    # fence never captures content from the next line.
    pattern: re.Pattern[str] = re.compile(
        r"( {,3})(:{3,})[^\n\S]*(.*?)[^\n\S]*$", re.MULTILINE
    )

    children: Sequence[Element]
    fence: str  # the opening colon run, e.g. ``":::"``
    attrs: str  # the raw attribute spec: ``{...}``, a bare class, or ``""``
    closer: str  # the closing colon run as written (may be shorter than ``fence``)
    prefix: str
    footnotes: dict[str, footnote.FootnoteDef]  # definitions made inside this div

    def __init__(self) -> None:  # pyright: ignore[reportMissingSuperCall]
        self.fence = ":::"
        self.attrs = ""
        self.closer = ":::"
        self.prefix = ""
        self.children = []
        # The body parses through its own `Source` rooted at this div (see
        # `parse` below), so this div is what `marko.ext.footnote.FootnoteDef.parse`
        # writes into when it registers a definition as
        # `source.root.footnotes[label]`. `marko.ext.footnote.Document` carries
        # the same mapping for the same reason; without it a footnote definition
        # inside a div raises `AttributeError` and aborts the run (#34).
        self.footnotes = {}

    @override
    @classmethod
    def match(cls, source: Source) -> re.Match[str] | None:
        m = source.expect_re(cls.pattern)
        if not m:
            return None
        prefix, fence, attrs = m.groups()
        source.context.div_info = (prefix, fence, attrs or "")
        return m

    @override
    @classmethod
    def parse(cls, source: Source) -> CustomFencedDiv:
        prefix, fence, attrs = source.context.div_info
        source.next_line()
        source.consume()

        # A fence line carrying an attribute spec opens a div; a bare colon run
        # closes one. Track depth so a nested div's closer does not terminate this
        # one -- otherwise the remainder of this div is parsed at top level and the
        # renderer emits a closer the source never had.
        closer_pat = re.compile(r" {,3}(:{3,})[^\n\S]*$")
        opener_pat = re.compile(r" {,3}:{3,}[^\n\S]*\S")
        # A colon run inside a fenced code block is literal text, not a fence, so
        # the div scan has to track code fences to know which lines to ignore.
        # Indented code blocks need no such handling: their four spaces already
        # fall outside the ` {,3}` prefix both fence patterns require.
        code_fence_pat = re.compile(r" {,3}(`{3,}|~{3,})(.*)$")

        lines: list[str] = []
        closer = fence
        depth = 0
        code_fence: str | None = None

        while not source.exhausted:
            line = _next_line(source)
            if line is None:
                break
            source.consume()
            code_match = code_fence_pat.match(line)
            if code_fence is not None:
                # Only a fence of the same character and at least the same length,
                # with nothing after it, closes the block (CommonMark 4.5).
                if (
                    code_match
                    and code_match.group(1)[0] == code_fence[0]
                    and len(code_match.group(1)) >= len(code_fence)
                    and not code_match.group(2).strip()
                ):
                    code_fence = None
            elif code_match and not (
                code_match.group(1)[0] == "`" and "`" in code_match.group(2)
            ):
                # A backtick fence's info string may not contain a backtick, which
                # is what keeps an inline code span from opening a block here.
                code_fence = code_match.group(1)
            else:
                closer_match = closer_pat.match(line)
                if closer_match:
                    if depth == 0:
                        closer = closer_match.group(1)
                        break
                    depth -= 1
                elif opener_pat.match(line):
                    depth += 1
            prefix_len = source.match_prefix(prefix, line)
            if prefix_len >= 0:
                line = line[prefix_len:]
            else:
                line = line.lstrip()
            lines.append(line)

        div = cls()
        div.fence, div.attrs, div.closer, div.prefix = fence, attrs, closer, prefix

        # The body is markdown, so parse it as blocks rather than keeping it as
        # opaque text (#20). It runs through a fresh `Source` rather than the
        # outer one because the scan above has already consumed the body's lines
        # in order to find the closing fence -- which is the part marko's own
        # block loop cannot do, since it does not know about div nesting or that
        # a colon run inside a code fence is not a fence.
        #
        # Inline parsing is not done here: `Parser.parse_inline` walks down from
        # the document root into any child that is a `BlockElement`, and these
        # are, so the div's contents are reached for free once the document is
        # built. Doing it here as well would parse them twice.
        body = Source("".join(lines))
        body.parser = source.parser
        with body.under_state(div):
            div.children = source.parser.parse_source(body)  # pyright: ignore[reportAttributeAccessIssue]
        return div

    @override
    @classmethod
    def get_type(cls, snake_case: bool = False) -> str:
        return "fenced_div" if snake_case else "FencedDiv"


class CustomLatexEnvironment(block.BlockElement):
    """
    LaTeX environment: ``\\begin{env}`` ... ``\\end{env}``.

    Content between the delimiters is preserved verbatim.  The opening
    ``\\begin`` line carries the environment name; the closer must be the
    matching ``\\end{env}``.
    """

    priority: int = 7
    parse_children: bool = True
    pattern: re.Pattern[str] = re.compile(
        r"( {,3})\\begin\{([^}]+)\}[^\n\S]*$", re.MULTILINE
    )

    children: Sequence[Element]
    env_name: str
    prefix: str

    def __init__(self, match: tuple[str, str, str]) -> None:
        self.env_name = match[0]
        self.prefix = match[1]
        self.children = [inline.RawText(match[2], False)]

    @override
    @classmethod
    def match(cls, source: Source) -> re.Match[str] | None:
        m = source.expect_re(cls.pattern)
        if not m:
            return None
        prefix, env_name = m.groups()
        source.context.latex_env_info = (prefix, env_name)
        return m

    @override
    @classmethod
    def parse(cls, source: Source) -> tuple[str, str, str]:
        prefix, env_name = source.context.latex_env_info
        source.next_line()
        source.consume()

        closer = rf"\\end{{{re.escape(env_name)}}}"
        closer_pat = re.compile(r" {,3}" + closer + r"\s*$")

        lines: list[str] = []
        while not source.exhausted:
            line = _next_line(source)
            if line is None:
                break
            source.consume()
            if closer_pat.match(line):
                break
            prefix_len = source.match_prefix(prefix, line)
            if prefix_len >= 0:
                line = line[prefix_len:]
            else:
                line = line.lstrip()
            lines.append(line)

        return (env_name, prefix, "".join(lines))

    @override
    @classmethod
    def get_type(cls, snake_case: bool = False) -> str:
        return "latex_environment" if snake_case else "LatexEnvironment"


class CustomDefinitionList(block.BlockElement):
    """
    Pandoc definition list, preserved verbatim.

    marko has no concept of pandoc's `definition_lists` extension (on by
    default for `-f markdown`), so a term line and its `:`/`~` definition
    lines parsed as one paragraph and rewrapping joined the marker
    mid-line, destroying the list (#10).  Same rule as raw TeX (#8) and
    subscript (#11): what can't be re-emitted faithfully must not be parsed
    apart, so the whole block is captured raw and re-emitted byte-identically.

    The shape mirrors pandoc's reader, probed empirically:

    - a definition marker is `:` or `~` indented at most TWO spaces, followed
      by whitespace (three spaces of indent makes it prose);
    - the term is a single non-marker line at block start, with at most ONE
      blank line before its first marker (two blanks make two paragraphs);
    - after a blank line the block continues only for a marker line, a
      four-space indented continuation, or another term/marker group.

    Pandoc's definition lists do NOT interrupt a paragraph (`text\\nTerm\\n: x`
    is one Para), so this element is deliberately absent from
    `CustomParagraph.break_paragraph`, and priority 2 keeps every other block
    construct (lists, headings, fences at priority >= 5) ahead of it: this is
    a refinement of the paragraph fallback only.
    """

    priority: int = 2
    parse_children: bool = False

    _MARKER: str = r" {0,2}[:~][ \t]"
    _TERM: str = rf" {{0,3}}(?!{_MARKER})\S[^\n]*"
    pattern: re.Pattern[str] = re.compile(rf"{_TERM}\n(?:[ \t]*\n)?(?={_MARKER})")
    # Matches only the blank line; everything after lives in the lookahead so
    # `consume()` advances past the blank alone.
    _BLANK_THEN_CONTINUATION: re.Pattern[str] = re.compile(
        rf"[ \t]*\n(?={_MARKER}| {{4}}|{_TERM}\n(?:[ \t]*\n)?{_MARKER})"
    )

    children: Sequence[Element]

    def __init__(self, match: str) -> None:
        self.children = [inline.RawText(match, False)]

    @override
    @classmethod
    def match(cls, source: Source) -> re.Match[str] | None:
        return source.expect_re(cls.pattern)

    @override
    @classmethod
    def parse(cls, source: Source) -> str:
        lines: list[str] = []
        while not source.exhausted:
            line = _next_line(source)
            if line is None:
                break
            if line.strip():
                source.consume()
                lines.append(line)
                continue
            if not source.expect_re(cls._BLANK_THEN_CONTINUATION):
                break
            source.consume()
            lines.append(line)
        return "".join(lines)

    @override
    @classmethod
    def get_type(cls, snake_case: bool = False) -> str:
        return "definition_list" if snake_case else "DefinitionList"


class CustomFootnoteDef(footnote.FootnoteDef):
    """
    Footnote definition that also accepts the label alone on its line.

    marko's pattern ends ``(?=\\S| {4})``, so it only matches when content or a
    four-space indent follows the colon on the same line. Pandoc also allows::

        [^1]:
            First para.

    Without this, the label line is not a definition at all and its indented body
    is parsed as an unrelated code block.
    """

    pattern: re.Pattern[str] = re.compile(
        r" {,3}\[\^([^\]]+)\]:[^\n\S]*(?=\S| {4}|\n|$)"
    )

    @override
    @classmethod
    def get_type(cls, snake_case: bool = False) -> str:
        # Must stay "FootnoteDef" so the renderer dispatches to
        # render_footnote_def and marko's footnote bookkeeping still finds it.
        return "footnote_def" if snake_case else "FootnoteDef"


class CustomParagraph(block.Paragraph):
    """
    Paragraph that also checks our custom block elements on continuation
    lines.  Marko's built-in ``break_paragraph`` only checks ``Quote``,
    ``Heading``, ``BlankLine``, and ``FencedCode`` — which means custom
    blocks (``DisplayMath``, ``FencedDiv``, ``LatexEnvironment``) never
    interrupt a paragraph and their content gets mangled by the wrapper.
    """

    @override
    @classmethod
    def break_paragraph(cls, source: Source, lazy: bool = False) -> bool:
        # Delegate to the original logic first.
        if block.Paragraph.break_paragraph(source, lazy):
            return True
        parser = source.parser
        # Also break when any of our custom block elements match. Calling
        # `.match()` mutates `source.match` (via `expect_re`), and the paragraph
        # parse loop derives `source.pos` from it on `consume()`. marko's own
        # `break_paragraph` saves and restores `source.match` for exactly this
        # reason; we must do the same here. Without the restore, a paragraph
        # whose inline code span straddles a hard line break drives marko's
        # parser into an infinite loop.
        prev_match = source.match
        # FootnoteDef is included so a definition on the line after another one
        # starts its own footnote instead of being swallowed as a lazy
        # continuation of the previous definition's paragraph. Pandoc requires no
        # blank line between consecutive definitions.
        keys = ("DisplayMath", "FencedDiv", "LatexEnvironment", "FootnoteDef")
        # Indexed directly, not guarded with `key in`: every one of these is
        # registered unconditionally in `_setup_extensions`, so a missing key means
        # setup is broken and should raise here rather than silently stop
        # interrupting paragraphs -- which is the very class of defect this fixes.
        matched = any(parser.block_elements[key].match(source) for key in keys)
        source.match = prev_match
        return matched

    @override
    @classmethod
    def get_type(cls, snake_case: bool = False) -> str:
        # Must return "paragraph" so the renderer dispatches to render_paragraph.
        # The default Element.get_type would return "custom_paragraph" since
        # we didn't set cls.override when subclassing.
        return "paragraph"


class CustomParser(Parser):
    inline_elements: dict[str, type[inline.InlineElement]]

    def __init__(self) -> None:
        super().__init__()
        self.block_elements["HTMLBlock"] = CustomHTMLBlock
        self.block_elements["FencedCode"] = CustomFencedCode
        self.block_elements["DisplayMath"] = CustomDisplayMath
        self.block_elements["FencedDiv"] = CustomFencedDiv
        self.block_elements["LatexEnvironment"] = CustomLatexEnvironment
        self.block_elements["DefinitionList"] = CustomDefinitionList
        # Override Paragraph so continuation lines also check our custom blocks
        self.block_elements["Paragraph"] = CustomParagraph
        reordered_inline_elements: dict[str, type[inline.InlineElement]] = {}
        for name, element in self.inline_elements.items():
            reordered_inline_elements[name] = element
            if name == "CodeSpan":
                reordered_inline_elements["InlineMath"] = CustomInlineMath
                reordered_inline_elements["RawInlineTex"] = CustomRawInlineTex
        assert "InlineMath" in reordered_inline_elements
        assert "RawInlineTex" in reordered_inline_elements
        self.inline_elements = reordered_inline_elements

    @override
    def parse(self, text: str) -> block.Document:
        refuse_if_present(text)
        return super().parse(text)


def flowmark_parser() -> CustomParser:
    """A marko parser configured the way flowmark reads Markdown."""
    parser = CustomParser()
    # Add GFM support, using our fixed Strikethrough with proper flanking rules.
    replacements: dict[type[Element], type[Element]] = {
        gfm_elements.Strikethrough: CustomStrikethrough,
        gfm_elements.Table: CustomTable,
        gfm_elements.TableRow: CustomTableRow,
        gfm_elements.TableCell: CustomTableCell,
    }
    for e in GFM.elements:
        e = replacements.get(e, e)
        assert e not in parser.block_elements and e not in parser.inline_elements
        parser.add_element(e)
    # Add GFM footnote support.
    footnote_ext = footnote.make_extension()
    for e in footnote_ext.elements:
        assert e not in parser.block_elements and e not in parser.inline_elements
        parser.add_element(e)
    # Accept pandoc's label-alone-on-its-line definition form.
    parser.block_elements["FootnoteDef"] = CustomFootnoteDef
    # GFM's Paragraph overwrites our CustomParagraph (same "Paragraph" key).
    # Re-register so that break_paragraph checks our custom block elements.
    parser.block_elements["Paragraph"] = CustomParagraph
    return parser
