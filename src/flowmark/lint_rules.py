"""Semantic and structural lint rules for Pandoc-flavoured Markdown.

Linting is deliberately separate from formatting.  This module owns defects that
canonical rendering cannot safely decide or repair: broken references, heading
structure, malformed Pandoc/TeX/math constructs, accessibility checks, frontmatter
integrity, and explicitly requested authoring policies.

Rules operate on the same source language Flowmark formats.  Inline code/math/raw TeX
and block code/math/TeX regions are protected before syntax-oriented scans run, so a
Markdown rule never interprets TeX punctuation as Markdown punctuation.  Source ranges
are always offsets into the original string and are converted to line/column positions
by the caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import unquote, urlsplit

from flowmark.atomic_spans import (
    INLINE_CODE_SPAN,
    PAIRED_HTML_COMMENT,
    PAIRED_JINJA_COMMENT,
    PAIRED_JINJA_TAG,
    PAIRED_JINJA_VAR,
    SINGLE_HTML_COMMENT,
    SINGLE_JINJA_COMMENT,
    SINGLE_JINJA_TAG,
    SINGLE_JINJA_VAR,
    iter_atomic_spans,
)
from flowmark.formats.flowmark_markdown import CustomRawInlineTex
from flowmark.pandoc_lint import (
    PandocJson,
    pandoc_math_sequence,
    pandoc_plain,
    parse_pandoc_for_lint,
    walk_pandoc,
)
from flowmark.pandoc_math import iter_pandoc_math_spans


class StyleRule(StrEnum):
    """Opt-in policies that are valid Markdown but may violate house style."""

    UNORDERED_LIST_MARKER = "unordered-list-marker"
    FENCE_MARKER = "fence-marker"
    BARE_URL = "bare-url"
    HEADING_PUNCTUATION = "heading-punctuation"
    REQUIRE_H1 = "require-h1"
    NO_INLINE_HTML = "no-inline-html"


@dataclass(frozen=True)
class RuleFinding:
    """One lint finding at a half-open source range."""

    rule: str
    severity: str
    message: str
    start: int
    end: int
    replacement: str | None = None


@dataclass(frozen=True)
class _Line:
    number: int
    start: int
    end: int
    raw_end: int
    text: str


@dataclass(frozen=True)
class _Fence:
    opening: _Line
    closing: _Line | None
    marker: str
    info: str
    content: tuple[_Line, ...]


@dataclass(frozen=True)
class _Heading:
    line: _Line
    level: int
    text: str
    start: int
    end: int
    explicit_id: str | None


@dataclass(frozen=True)
class _Frontmatter:
    opening: _Line
    closing: _Line | None
    body: tuple[_Line, ...]


_ATX_HEADING = re.compile(r"^(?P<indent> {0,3})(?P<marks>#+)(?:[ \t]+|$)(?P<body>.*)$")
_SETEXT_UNDERLINE = re.compile(r"^ {0,3}(?P<marks>=+|-+)[ \t]*$")
_ATTR_ID = re.compile(r"(?:^|\s)#(?P<id>[A-Za-z][A-Za-z0-9_.:-]*)")
_FENCE_OPEN = re.compile(r"^(?P<indent> {0,3})(?P<marker>`{3,}|~{3,})(?P<info>.*)$")
_LATEX_BEGIN = re.compile(r"\\begin\{(?P<name>[A-Za-z*]+)\}")
_LATEX_END_TEMPLATE = r"\\end\{%s\}"
_BARE_URL = re.compile(r"(?<![<\w])(https?://[^\s<>]+)")
_INLINE_HTML = re.compile(r"</?[A-Za-z][^>\n]*>")
_UNORDERED_MARKER = re.compile(r"^(?P<indent> *)(?P<marker>[*+-])[ \t]+")
_REPEATED_MATH_SCRIPT = re.compile(r"(?<!\\)(?P<script>[_^])(?:\\[A-Za-z@]+|\\.|[A-Za-z0-9])[ \t]*(?P=script)")

_MATH_OPERATOR_NAMES = (
    "arccos",
    "arcsin",
    "arctan",
    "argmax",
    "argmin",
    "liminf",
    "limsup",
    "coker",
    "codim",
    "cosh",
    "coth",
    "csch",
    "sech",
    "sinh",
    "tanh",
    "Spec",
    "Proj",
    "Hom",
    "Ext",
    "Tor",
    "Aut",
    "End",
    "Pic",
    "Gal",
    "PGL",
    "PSL",
    "rank",
    "char",
    "dim",
    "deg",
    "det",
    "gcd",
    "lcm",
    "ker",
    "lim",
    "sup",
    "inf",
    "max",
    "min",
    "sin",
    "cos",
    "tan",
    "cot",
    "sec",
    "csc",
    "log",
    "ln",
    "exp",
    "arg",
    "GL",
    "SL",
    "SO",
    "SU",
    "Sp",
)
_BARE_MATH_OPERATOR = re.compile(r"(?<![A-Za-z\\])(?P<name>" + "|".join(re.escape(name) for name in _MATH_OPERATOR_NAMES) + r")(?![A-Za-z])")
_ROMANIZED_MATH_TEXT = re.compile(
    r"\\(?:operatorname|mathrm|textrm|text|mathsf|mathtt|mathbf|mathit)\*?"
    r"[ \t]*\{(?:\\.|[^{}])*\}"
)
_LEFT_RIGHT = re.compile(r"(?<!\\)\\(?P<kind>left|right)\b")

_PROTECTED_INLINE_PATTERNS = (
    INLINE_CODE_SPAN,
    SINGLE_HTML_COMMENT,
    PAIRED_HTML_COMMENT,
    SINGLE_JINJA_TAG,
    PAIRED_JINJA_TAG,
    SINGLE_JINJA_COMMENT,
    PAIRED_JINJA_COMMENT,
    SINGLE_JINJA_VAR,
    PAIRED_JINJA_VAR,
)

_LITERAL_ONLY_PATTERNS = (
    INLINE_CODE_SPAN,
    SINGLE_HTML_COMMENT,
    PAIRED_HTML_COMMENT,
    SINGLE_JINJA_TAG,
    PAIRED_JINJA_TAG,
    SINGLE_JINJA_COMMENT,
    PAIRED_JINJA_COMMENT,
    SINGLE_JINJA_VAR,
    PAIRED_JINJA_VAR,
)

_NON_DESCRIPTIVE_LINK_TEXT = {
    "click here",
    "here",
    "link",
    "this link",
    "more",
    "read more",
    "learn more",
}

_HEADING_PUNCTUATION = frozenset(".,;:!?")


def _lines(text: str) -> list[_Line]:
    raw_lines = text.splitlines(keepends=True)
    if not raw_lines:
        return [_Line(1, 0, 0, 0, "")]
    result: list[_Line] = []
    offset = 0
    for number, raw in enumerate(raw_lines, 1):
        visible = raw.rstrip("\r\n")
        result.append(
            _Line(
                number=number,
                start=offset,
                end=offset + len(visible),
                raw_end=offset + len(raw),
                text=visible,
            )
        )
        offset += len(raw)
    return result


def _frontmatter(lines: list[_Line]) -> _Frontmatter | None:
    start = 0
    while start < len(lines) and not lines[start].text.strip():
        start += 1
    if start >= len(lines) or lines[start].text.strip() != "---":
        return None
    body: list[_Line] = []
    for index in range(start + 1, len(lines)):
        if lines[index].text.strip() in {"---", "..."}:
            return _Frontmatter(lines[start], lines[index], tuple(body))
        body.append(lines[index])
    return _Frontmatter(lines[start], None, tuple(body))


def _fences(lines: list[_Line], protected_line_numbers: set[int]) -> list[_Fence]:
    result: list[_Fence] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.number in protected_line_numbers:
            index += 1
            continue
        match = _FENCE_OPEN.match(line.text)
        if match is None:
            index += 1
            continue
        marker = match.group("marker")
        # A backtick info string may not itself contain a backtick.
        if marker[0] == "`" and "`" in match.group("info"):
            index += 1
            continue
        content: list[_Line] = []
        closing: _Line | None = None
        probe = index + 1
        while probe < len(lines):
            candidate = lines[probe]
            stripped = candidate.text.lstrip(" ")
            leading = len(candidate.text) - len(stripped)
            if leading <= 3:
                close_match = re.match(rf"{re.escape(marker[0])}{{{len(marker)},}}[ \t]*$", stripped)
                if close_match is not None:
                    closing = candidate
                    break
            content.append(candidate)
            probe += 1
        result.append(_Fence(line, closing, marker, match.group("info").strip(), tuple(content)))
        index = (probe + 1) if closing is not None else len(lines)
    return result


def _mark(protected: bytearray, start: int, end: int) -> None:
    if end <= start:
        return
    protected[start:end] = b"\x01" * (end - start)


def _build_protected_map(
    text: str,
    lines: list[_Line],
    frontmatter: _Frontmatter | None,
    fences: list[_Fence],
) -> bytearray:
    protected = bytearray(len(text))
    if frontmatter is not None and frontmatter.closing is not None:
        last = frontmatter.closing
        _mark(protected, frontmatter.opening.start, last.raw_end)

    for fence in fences:
        if fence.closing is not None:
            _mark(protected, fence.opening.start, fence.closing.raw_end)

    # Raw LaTeX environments are verbatim from the Markdown linter's point of
    # view. Math itself is marked below by the Pandoc-derived scanner; do not
    # recreate its block/inline boundary rules here.
    index = 0
    while index < len(lines):
        line = lines[index]
        begin = _LATEX_BEGIN.search(line.text)
        if begin is not None:
            close_re = re.compile(_LATEX_END_TEMPLATE % re.escape(begin.group("name")))
            probe = index
            while probe < len(lines):
                if close_re.search(lines[probe].text) is not None:
                    _mark(protected, line.start + begin.start(), lines[probe].raw_end)
                    index = probe + 1
                    break
                probe += 1
            else:
                index += 1
            continue
        index += 1

    for span in iter_atomic_spans(text, _PROTECTED_INLINE_PATTERNS):
        if span.is_atomic:
            _mark(protected, span.start, span.end)

    literal = _build_literal_protected_map(text, frontmatter, fences)
    for span in iter_pandoc_math_spans(text, blocked=literal):
        _mark(protected, span.start, span.end)

    raw_tex_pattern = CustomRawInlineTex.pattern
    if isinstance(raw_tex_pattern, re.Pattern):
        for match in raw_tex_pattern.finditer(text):
            _mark(protected, match.start(), match.end())
    return protected


def _build_literal_protected_map(
    text: str,
    frontmatter: _Frontmatter | None,
    fences: list[_Fence],
) -> bytearray:
    """Protect regions where TeX-looking source is literal rather than authored TeX."""
    protected = bytearray(len(text))
    if frontmatter is not None and frontmatter.closing is not None:
        last = frontmatter.closing
        _mark(protected, frontmatter.opening.start, last.raw_end)
    for fence in fences:
        if fence.closing is not None:
            _mark(protected, fence.opening.start, fence.closing.raw_end)
    for span in iter_atomic_spans(text, _LITERAL_ONLY_PATTERNS):
        if span.is_atomic:
            _mark(protected, span.start, span.end)
    return protected


def _math_regions(
    text: str,
    pandoc_document: dict[str, PandocJson],
) -> list[tuple[int, int]]:
    """Locate only source spans which reconcile to actual Pandoc ``Math`` nodes."""
    expected = pandoc_math_sequence(pandoc_document)
    if not expected:
        return []

    candidates = list(iter_pandoc_math_spans(text))
    regions: list[tuple[int, int]] = []
    cursor = 0
    for display, equation in expected:
        while cursor < len(candidates):
            candidate = candidates[cursor]
            cursor += 1
            if candidate.display == display and candidate.equation == equation:
                regions.append((candidate.content_start, candidate.content_end))
                break
        else:
            # The AST is authoritative. If the source locator cannot reproduce
            # one node, decline source-local diagnostics for that node instead
            # of guessing where it came from.
            break
    return regions


def _mask_romanized_math(text: str) -> str:
    """Mask explicit text/operator wrappers while preserving source offsets."""
    chars = list(text)
    for match in _ROMANIZED_MATH_TEXT.finditer(text):
        chars[match.start() : match.end()] = " " * (match.end() - match.start())
    return "".join(chars)


def _mask_tex_comments(text: str) -> str:
    """Blank TeX comments while preserving offsets/newlines."""
    chars = list(text)
    index = 0
    while index < len(chars):
        if chars[index] != "%":
            index += 1
            continue
        backslashes = 0
        probe = index - 1
        while probe >= 0 and chars[probe] == "\\":
            backslashes += 1
            probe -= 1
        if backslashes % 2 == 1:
            index += 1
            continue
        end = text.find("\n", index)
        if end < 0:
            end = len(chars)
        chars[index:end] = " " * (end - index)
        index = end
    return "".join(chars)


def _tex_group_findings(source: str, source_offset: int) -> list[RuleFinding]:
    """Check TeX grouping and left/right pairing inside one math region."""
    findings: list[RuleFinding] = []
    visible = _mask_tex_comments(source)
    groups: list[int] = []
    index = 0
    while index < len(visible):
        char = visible[index]
        if char == "\\" and index + 1 < len(visible) and visible[index + 1] in "{}%":
            index += 2
            continue
        if char == "{":
            groups.append(index)
        elif char == "}":
            if groups:
                groups.pop()
            else:
                findings.append(
                    RuleFinding(
                        "math/unmatched-group-close",
                        "error",
                        "TeX group closes with '}' here but no matching '{' is open.",
                        source_offset + index,
                        source_offset + index + 1,
                    )
                )
        index += 1
    for opening in groups:
        findings.append(
            RuleFinding(
                "math/unclosed-group",
                "error",
                "TeX group opens with '{' here but is never closed.",
                source_offset + opening,
                source_offset + opening + 1,
            )
        )

    left_stack: list[re.Match[str]] = []
    for match in _LEFT_RIGHT.finditer(visible):
        if match.group("kind") == "left":
            left_stack.append(match)
        elif left_stack:
            left_stack.pop()
        else:
            findings.append(
                RuleFinding(
                    "math/unmatched-right",
                    "error",
                    "\\right appears here without a matching \\left.",
                    source_offset + match.start(),
                    source_offset + match.end(),
                )
            )
    for match in left_stack:
        findings.append(
            RuleFinding(
                "math/unclosed-left",
                "error",
                "\\left appears here without a matching \\right.",
                source_offset + match.start(),
                source_offset + match.end(),
            )
        )
    return findings


def _mathematical_findings(
    text: str,
    pandoc_document: dict[str, PandocJson],
) -> list[RuleFinding]:
    """High-confidence TeX/math diagnostics that normalization cannot repair."""
    findings: list[RuleFinding] = []
    for start, end in _math_regions(text, pandoc_document):
        source = text[start:end]
        findings.extend(_tex_group_findings(source, start))
        for match in _REPEATED_MATH_SCRIPT.finditer(source):
            script = match.group("script")
            second = start + match.end() - 1
            kind = "subscript" if script == "_" else "superscript"
            findings.append(
                RuleFinding(
                    f"math/repeated-{kind}",
                    "error",
                    f"Repeated unbraced {kind} operator; TeX rejects this as a double {kind}.",
                    second,
                    second + 1,
                )
            )

        visible = _mask_romanized_math(source)
        for match in _BARE_MATH_OPERATOR.finditer(visible):
            name = match.group("name")
            findings.append(
                RuleFinding(
                    "math/bare-operator",
                    "warning",
                    f"Math operator {name!r} is written as ordinary variables; use its semantic operator macro or \\operatorname{{{name}}}.",
                    start + match.start("name"),
                    start + match.end("name"),
                )
            )
    return findings


def _overlaps(protected: bytearray, start: int, end: int) -> bool:
    if end <= start:
        return False
    return any(protected[start:end])


def _strip_heading_attributes(text: str) -> tuple[str, str | None]:
    stripped = text.strip()
    explicit_id: str | None = None
    match = re.search(r"[ \t]+\{(?P<body>[^{}\n]*)\}[ \t]*$", stripped)
    if match is not None:
        id_match = _ATTR_ID.search(match.group("body"))
        if id_match is not None:
            explicit_id = id_match.group("id")
        stripped = stripped[: match.start()].rstrip()
    # ATX closing sequence is syntax only when preceded by whitespace.
    stripped = re.sub(r"[ \t]+#+[ \t]*$", "", stripped).rstrip()
    return stripped, explicit_id


def _headings(lines: list[_Line], protected: bytearray, frontmatter: _Frontmatter | None) -> list[_Heading]:
    result: list[_Heading] = []
    frontmatter_lines: set[int] = set()
    if frontmatter is not None:
        end = frontmatter.closing.number if frontmatter.closing is not None else lines[-1].number
        frontmatter_lines.update(range(frontmatter.opening.number, end + 1))

    consumed_setext_underlines: set[int] = set()
    for index, line in enumerate(lines):
        if line.number in frontmatter_lines or _overlaps(protected, line.start, line.end):
            continue
        match = _ATX_HEADING.match(line.text)
        if match is not None:
            body, explicit_id = _strip_heading_attributes(match.group("body"))
            result.append(
                _Heading(
                    line=line,
                    level=len(match.group("marks")),
                    text=body,
                    start=line.start + match.start("marks"),
                    end=line.end,
                    explicit_id=explicit_id,
                )
            )
            continue
        if index + 1 >= len(lines):
            continue
        underline = lines[index + 1]
        if underline.number in frontmatter_lines or _overlaps(protected, underline.start, underline.end):
            continue
        underline_match = _SETEXT_UNDERLINE.match(underline.text)
        if underline_match is None or not line.text.strip():
            continue
        # Setext headings only arise from paragraph-ish source.  Exclude obvious
        # block openers so an HR below a list/fence is not reclassified here.
        if re.match(r"^ {0,3}(?:>|[*+] |\d+[.)] |```|~~~|:::)", line.text):
            continue
        body, explicit_id = _strip_heading_attributes(line.text)
        result.append(
            _Heading(
                line=line,
                level=1 if underline_match.group("marks")[0] == "=" else 2,
                text=body,
                start=line.start,
                end=underline.end,
                explicit_id=explicit_id,
            )
        )
        consumed_setext_underlines.add(underline.number)
    return result


def _plain_inline_text(text: str) -> str:
    text = re.sub(r"`+([^`]+)`+", r"\1", text)
    text = re.sub(r"!?(?:\[([^\]]*)\])\([^)]*\)", r"\1", text)
    text = re.sub(r"!?(?:\[([^\]]*)\])\[[^\]]*\]", r"\1", text)
    text = re.sub(r"[*_~]", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(text.split())


def _pandoc_attr(value: PandocJson) -> tuple[str, list[str], list[tuple[str, str]]] | None:
    if not isinstance(value, list) or len(value) != 3:
        return None
    identifier, classes, key_values = value
    if not isinstance(identifier, str) or not isinstance(classes, list) or not isinstance(key_values, list):
        return None
    parsed_classes = [item for item in classes if isinstance(item, str)]
    parsed_key_values: list[tuple[str, str]] = []
    for item in key_values:
        if (
            isinstance(item, list)
            and len(item) == 2
            and isinstance(item[0], str)
            and isinstance(item[1], str)
        ):
            parsed_key_values.append((item[0], item[1]))
    return identifier, parsed_classes, parsed_key_values


def _pandoc_node_attr(node: dict[str, PandocJson]) -> tuple[str, list[str], list[tuple[str, str]]] | None:
    kind = node.get("t")
    content = node.get("c")
    if not isinstance(content, list):
        return None
    attr_index = {
        "Header": 1,
        "CodeBlock": 0,
        "Div": 0,
        "Span": 0,
        "Link": 0,
        "Image": 0,
        "Table": 0,
    }.get(kind if isinstance(kind, str) else "")
    if attr_index is None or attr_index >= len(content):
        return None
    return _pandoc_attr(content[attr_index])


def _pandoc_headers(document: dict[str, PandocJson]) -> list[tuple[int, str, str]]:
    result: list[tuple[int, str, str]] = []
    for node in walk_pandoc(document):
        if node.get("t") != "Header":
            continue
        content = node.get("c")
        if not isinstance(content, list) or len(content) != 3 or not isinstance(content[0], int):
            continue
        attr = _pandoc_attr(content[1])
        identifier = "" if attr is None else attr[0]
        result.append((content[0], " ".join(pandoc_plain(content[2]).split()), identifier))
    return result


def _reconcile_heading_locations(
    headers: list[tuple[int, str, str]],
    candidates: list[_Heading],
) -> list[tuple[int, int]]:
    """Map Pandoc-proven headers to local source candidates without creating syntax."""
    locations: list[tuple[int, int]] = []
    cursor = 0
    for level, text, _identifier in headers:
        wanted = text.casefold()
        found: _Heading | None = None
        while cursor < len(candidates):
            candidate = candidates[cursor]
            cursor += 1
            if candidate.level != level:
                continue
            if _plain_inline_text(candidate.text).casefold() != wanted:
                continue
            found = candidate
            break
        locations.append((0, 0) if found is None else (found.start, found.end))
    return locations


def _pandoc_identifiers(document: dict[str, PandocJson]) -> list[str]:
    result: list[str] = []
    for node in walk_pandoc(document):
        attr = _pandoc_node_attr(node)
        if attr is not None and attr[0]:
            result.append(attr[0])
    return result


def _locate_after(text: str, needles: tuple[str, ...], start: int = 0) -> tuple[int, int]:
    best: tuple[int, int] | None = None
    for needle in needles:
        if not needle:
            continue
        offset = text.find(needle, start)
        if offset < 0:
            continue
        candidate = (offset, offset + len(needle))
        if best is None or candidate[0] < best[0]:
            best = candidate
    return best or (0, 0)


def _pandoc_code_blocks(
    document: dict[str, PandocJson],
) -> list[tuple[tuple[str, list[str], list[tuple[str, str]]], str]]:
    result: list[tuple[tuple[str, list[str], list[tuple[str, str]]], str]] = []
    for node in walk_pandoc(document):
        if node.get("t") != "CodeBlock":
            continue
        content = node.get("c")
        if not isinstance(content, list) or len(content) != 2 or not isinstance(content[1], str):
            continue
        attr = _pandoc_attr(content[0])
        if attr is None:
            continue
        result.append((attr, content[1]))
    return result


def _fence_source_text(fence: _Fence) -> str:
    opening_indent = len(fence.opening.text) - len(fence.opening.text.lstrip(" "))
    content: list[str] = []
    for line in fence.content:
        text = line.text
        drop = 0
        while drop < min(opening_indent, len(text)) and text[drop] == " ":
            drop += 1
        content.append(text[drop:])
    return "\n".join(content).expandtabs(4)


def _reconciled_fences(
    document: dict[str, PandocJson],
    fences: list[_Fence],
) -> list[tuple[_Fence, tuple[str, list[str], list[tuple[str, str]]], str]]:
    """Pair source fences with actual Pandoc CodeBlocks; unmatched source is ignored."""
    candidates = [fence for fence in fences if fence.closing is not None]
    cursor = 0
    result: list[tuple[_Fence, tuple[str, list[str], list[tuple[str, str]]], str]] = []
    for attr, code in _pandoc_code_blocks(document):
        found: _Fence | None = None
        while cursor < len(candidates):
            candidate = candidates[cursor]
            cursor += 1
            if _fence_source_text(candidate) == code:
                found = candidate
                break
        if found is not None:
            result.append((found, attr, code))
    return result


def _meta_strings(value: PandocJson) -> list[str]:
    """Flatten scalar/list metadata values exactly as exposed by Pandoc JSON."""
    if not isinstance(value, dict):
        return []
    kind = value.get("t")
    content = value.get("c")
    if kind == "MetaString" and isinstance(content, str):
        return [content]
    if kind == "MetaInlines":
        return [" ".join(pandoc_plain(content).split())]
    if kind == "MetaList" and isinstance(content, list):
        result: list[str] = []
        for item in content:
            result.extend(_meta_strings(item))
        return result
    return []


def _pandoc_resource_findings(
    text: str,
    pandoc_document: dict[str, PandocJson],
    source_path: Path | None,
) -> list[RuleFinding]:
    if source_path is None:
        return []
    meta = pandoc_document.get("meta")
    if not isinstance(meta, dict):
        return []
    findings: list[RuleFinding] = []
    search_from = 0
    for key in (
        "bibliography",
        "csl",
        "template",
        "include-in-header",
        "include-before-body",
        "include-after-body",
    ):
        value = meta.get(key)
        if value is None:
            continue
        for resource in _meta_strings(value):
            if not _is_explicit_local_resource(resource):
                continue
            if _resolve_local_resource(source_path, resource).exists():
                continue
            start, end = _locate_after(text, (resource,), search_from)
            if end > start:
                search_from = end
            findings.append(
                RuleFinding(
                    "pandoc/missing-resource",
                    "warning",
                    f"Pandoc frontmatter resource {resource!r} does not exist relative to this document.",
                    start,
                    end,
                )
            )
    return findings


def _pandoc_semantic_findings(
    text: str,
    pandoc_document: dict[str, PandocJson],
    lines: list[_Line],
    frontmatter: _Frontmatter | None,
    fences: list[_Fence],
    protected: bytearray,
    styles: frozenset[StyleRule],
    source_path: Path | None,
) -> list[RuleFinding]:
    """Semantic lint rules over constructs whose existence Pandoc already proved."""
    findings: list[RuleFinding] = []

    headers = _pandoc_headers(pandoc_document)
    local_headers = _headings(lines, protected, frontmatter)
    header_locations = _reconcile_heading_locations(headers, local_headers)
    previous_level: int | None = None
    seen_heading_text: dict[str, int] = {}
    h1_count = 0
    for index, (level, title, _identifier) in enumerate(headers):
        start, end = header_locations[index]
        if previous_level is not None and level > previous_level + 1:
            findings.append(
                RuleFinding(
                    "heading/increment",
                    "warning",
                    f"Heading level jumps from H{previous_level} to H{level}.",
                    start,
                    end,
                )
            )
        previous_level = level
        normalized_title = title.casefold()
        if normalized_title:
            if normalized_title in seen_heading_text:
                findings.append(
                    RuleFinding(
                        "heading/duplicate",
                        "warning",
                        f"Heading {title!r} duplicates an earlier heading.",
                        start,
                        end,
                    )
                )
            else:
                seen_heading_text[normalized_title] = index
        if level == 1:
            h1_count += 1
            if h1_count > 1:
                findings.append(
                    RuleFinding(
                        "heading/multiple-h1",
                        "warning",
                        "Document contains more than one level-1 heading.",
                        start,
                        end,
                    )
                )
        if StyleRule.HEADING_PUNCTUATION in styles and title.rstrip().endswith(tuple(_HEADING_PUNCTUATION)):
            findings.append(
                RuleFinding(
                    "style/heading-punctuation",
                    "warning",
                    "Heading ends in punctuation.",
                    start,
                    end,
                )
            )
    if StyleRule.REQUIRE_H1 in styles and h1_count == 0:
        first = next((line for line in lines if line.text.strip()), lines[0])
        findings.append(
            RuleFinding(
                "style/required-h1",
                "warning",
                "Document contains no level-1 heading.",
                first.start,
                first.end,
            )
        )

    for fence, _attr, _code in _reconciled_fences(pandoc_document, fences):
        if _fence_language(fence.info) is None:
            findings.append(
                RuleFinding(
                    "code/missing-language",
                    "warning",
                    "Fenced code block has no language/info class.",
                    fence.opening.start,
                    fence.opening.end,
                )
            )
        for line in fence.content:
            if "\t" not in line.text:
                continue
            column = line.text.index("\t")
            findings.append(
                RuleFinding(
                    "code/hard-tab",
                    "warning",
                    "Fenced code block contains a hard tab.",
                    line.start + column,
                    line.start + column + 1,
                )
            )

    seen_ids: set[str] = set()
    id_search_from = 0
    all_ids = set(_pandoc_identifiers(pandoc_document))
    for identifier in _pandoc_identifiers(pandoc_document):
        start, end = _locate_after(text, (f"#{identifier}", f'id="{identifier}"', f"id={identifier}"), id_search_from)
        if end > start:
            id_search_from = end
        if identifier in seen_ids:
            findings.append(
                RuleFinding(
                    "pandoc/duplicate-identifier",
                    "error",
                    f"Pandoc identifier {identifier!r} is used more than once.",
                    start,
                    end,
                )
            )
        else:
            seen_ids.add(identifier)

    link_search_from = 0
    for node in walk_pandoc(pandoc_document):
        kind = node.get("t")
        if kind not in {"Link", "Image"}:
            continue
        content = node.get("c")
        if not isinstance(content, list) or len(content) != 3:
            continue
        label = " ".join(pandoc_plain(content[1]).split())
        target = content[2]
        if not isinstance(target, list) or len(target) != 2 or not isinstance(target[0], str):
            continue
        destination = target[0]
        start, end = _locate_after(
            text,
            (destination, label, "![]" if kind == "Image" and not label else "", "]()" if not destination else ""),
            link_search_from,
        )
        if end > start:
            link_search_from = end

        if kind == "Image" and not label:
            findings.append(
                RuleFinding(
                    "accessibility/image-alt",
                    "warning",
                    "Image has empty alternative text.",
                    start,
                    end,
                )
            )
        if kind == "Link" and destination == "":
            findings.append(
                RuleFinding(
                    "link/empty-destination",
                    "warning",
                    "Link has an empty destination.",
                    start,
                    end,
                )
            )
        if kind == "Link" and label.casefold() in _NON_DESCRIPTIVE_LINK_TEXT:
            findings.append(
                RuleFinding(
                    "link/non-descriptive-text",
                    "warning",
                    f"Link text {label!r} does not describe its destination.",
                    start,
                    end,
                )
            )
        if kind == "Link" and destination.startswith("#"):
            fragment = unquote(destination[1:])
            if fragment and fragment not in all_ids:
                findings.append(
                    RuleFinding(
                        "link/invalid-fragment",
                        "warning",
                        f"Local fragment '#{fragment}' does not match a Pandoc identifier in this document.",
                        start,
                        end,
                    )
                )
        if kind == "Link":
            local_finding = _local_destination_finding(destination, start, end, source_path)
            if local_finding is not None:
                findings.append(local_finding)

    return findings


def _fence_language(info: str) -> str | None:
    info = info.strip()
    if not info:
        return None
    if not info.startswith("{"):
        return info.split()[0]
    match = re.search(r"(?:^|\s)\.([A-Za-z0-9_+.-]+)", info.strip("{}"))
    return match.group(1) if match is not None else None


def _is_explicit_local_resource(value: str) -> bool:
    """Whether static existence is meaningful without TeX/Pandoc search paths."""
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return False
    if any(token in value for token in ("$", "{{", "}}", "\\")):
        return False
    path = Path(unquote(parsed.path))
    return value.startswith(("./", "../")) or "/" in value or bool(path.suffix)


def _resolve_local_resource(source_path: Path, value: str) -> Path:
    resource = Path(unquote(urlsplit(value).path))
    return resource if resource.is_absolute() else source_path.parent / resource


def _target_pandoc_ids(path: Path) -> set[str] | None:
    try:
        target_text = path.read_text()
    except OSError, UnicodeError:
        return None
    parsed = parse_pandoc_for_lint(target_text)
    if parsed.document is None:
        return None
    return set(_pandoc_identifiers(parsed.document))


def _local_destination_finding(
    destination: str,
    start: int,
    end: int,
    source_path: Path | None,
) -> RuleFinding | None:
    if source_path is None or not destination or destination.startswith("#"):
        return None
    parsed = urlsplit(destination)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None
    relative = Path(unquote(parsed.path))
    target = relative if relative.is_absolute() else source_path.parent / relative
    if not target.exists():
        return RuleFinding(
            "link/missing-local-target",
            "warning",
            f"Local link target {parsed.path!r} does not exist relative to this document.",
            start,
            end,
        )
    if not parsed.fragment or not target.is_file():
        return None
    if target.suffix.casefold() not in {".md", ".markdown", ".mdown", ".mkd"}:
        return None
    identifiers = _target_pandoc_ids(target)
    fragment = unquote(parsed.fragment)
    if identifiers is None or fragment in identifiers:
        return None
    return RuleFinding(
        "link/invalid-fragment",
        "warning",
        f"Fragment '#{fragment}' does not match a heading identifier in {parsed.path!r}.",
        start,
        end,
    )


def _style_findings(
    text: str,
    lines: list[_Line],
    fences: list[_Fence],
    protected: bytearray,
    styles: frozenset[StyleRule],
    max_line_length: int | None,
) -> list[RuleFinding]:
    findings: list[RuleFinding] = []
    if StyleRule.FENCE_MARKER in styles:
        seen_marker: str | None = None
        for fence in fences:
            if fence.closing is None:
                continue
            marker = fence.marker[0]
            if seen_marker is None:
                seen_marker = marker
            elif marker != seen_marker:
                findings.append(
                    RuleFinding(
                        "style/fence-marker",
                        "warning",
                        "Code fence marker is inconsistent with the first fence in the document.",
                        fence.opening.start,
                        fence.opening.end,
                    )
                )
    if StyleRule.BARE_URL in styles:
        for match in _BARE_URL.finditer(text):
            if _overlaps(protected, match.start(), match.end()):
                continue
            findings.append(
                RuleFinding(
                    "style/bare-url",
                    "warning",
                    "Bare URL is disallowed by the selected lint style.",
                    match.start(),
                    match.end(),
                )
            )
    if StyleRule.UNORDERED_LIST_MARKER in styles:
        markers_by_indent: dict[int, str] = {}
        for line in lines:
            if _overlaps(protected, line.start, line.end):
                continue
            match = _UNORDERED_MARKER.match(line.text)
            if match is None:
                continue
            indent = len(match.group("indent"))
            marker = match.group("marker")
            expected = markers_by_indent.setdefault(indent, marker)
            if marker != expected:
                findings.append(
                    RuleFinding(
                        "style/unordered-list-marker",
                        "warning",
                        f"Unordered-list marker {marker!r} is inconsistent with {expected!r} at this nesting level.",
                        line.start + match.start("marker"),
                        line.start + match.end("marker"),
                    )
                )
    if StyleRule.NO_INLINE_HTML in styles:
        for match in _INLINE_HTML.finditer(text):
            if _overlaps(protected, match.start(), match.end()):
                continue
            findings.append(
                RuleFinding(
                    "style/no-inline-html",
                    "warning",
                    "Inline HTML is disallowed by the selected lint style.",
                    match.start(),
                    match.end(),
                )
            )
    if max_line_length is not None and max_line_length > 0:
        for line in lines:
            if len(line.text) <= max_line_length or _overlaps(protected, line.start, line.end):
                continue
            findings.append(
                RuleFinding(
                    "style/line-length",
                    "warning",
                    f"Line is {len(line.text)} characters; configured maximum is {max_line_length}.",
                    line.start + max_line_length,
                    line.end,
                )
            )
    return findings


def lint_rule_findings(
    text: str,
    *,
    pandoc_document: dict[str, PandocJson],
    source_path: Path | None = None,
    styles: frozenset[StyleRule] | None = None,
    max_line_length: int | None = None,
) -> list[RuleFinding]:
    """Run explicit semantic/structural lint rules over ``text``."""
    styles = styles or frozenset()
    lines = _lines(text)
    frontmatter = _frontmatter(lines)
    frontmatter_line_numbers: set[int] = set()
    if frontmatter is not None:
        last_number = frontmatter.closing.number if frontmatter.closing is not None else lines[-1].number
        frontmatter_line_numbers.update(range(frontmatter.opening.number, last_number + 1))
    fences = _fences(lines, frontmatter_line_numbers)
    protected = _build_protected_map(text, lines, frontmatter, fences)

    findings = [
        *_pandoc_semantic_findings(
            text,
            pandoc_document,
            lines,
            frontmatter,
            fences,
            protected,
            styles,
            source_path,
        ),
        *_pandoc_resource_findings(text, pandoc_document, source_path),
        *_mathematical_findings(text, pandoc_document),
        *_style_findings(text, lines, fences, protected, styles, max_line_length),
    ]
    # Identical findings can arise when one malformed token is recognized by a
    # generic and a family-specific scan.  Preserve the most specific first one.
    deduplicated: dict[tuple[str, int, int, str], RuleFinding] = {}
    for finding in findings:
        deduplicated.setdefault((finding.rule, finding.start, finding.end, finding.message), finding)
    return sorted(
        deduplicated.values(),
        key=lambda finding: (finding.start, finding.end, finding.rule),
    )


__all__ = ("RuleFinding", "StyleRule", "lint_rule_findings")
