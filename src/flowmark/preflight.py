"""
Cheap checks for input that was already ambiguous before flowmark touched it.

When verification fails there are two different questions: *did flowmark break
this?* and *was this already broken?*  The pandoc gate can only ask the first, so
on input that was already broken -- a fence never closed, a table row with more
cells than its header -- it reports a flowmark bug that no report can fix.

So these run only when verification has already failed, and only to say "here is
something in your input that pandoc reads differently than you probably meant".
They never gate a run on their own and they never fire on a document that verified.

**Precision over recall.**  A check that fires on ordinary markdown would relabel
every real flowmark defect as the user's fault, which is worse than the message it
replaces.  Each check below is written to be quiet unless it is fairly sure, and
`test_preflight_is_quiet_on_clean_input` is what holds that line.  Missing a
malformed document costs today's message; a false positive costs the truth.  A
check must state a rule pandoc actually applies, verified against pandoc itself.

The same checks are importable on their own, so a document can be checked without
reformatting it -- problem 3 in #17 was breaking the reporter's pandoc build before
flowmark ever ran.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from flowmark.formats.flowmark_parser import split_pipe_table_row
from flowmark.linewrapping.atomic_patterns import DOLLAR_MATH


class MalformedInputError(ValueError):
    """Raised when the document has an error flowmark will not format around."""


@dataclass(frozen=True)
class Finding:
    """One suspect construct, at the 1-based line where it appears."""

    line: int
    message: str


# A table row is a line whose stripped form starts and ends with `|`. That is
# stricter than GFM needs, but a leading-pipe-only row is rare enough that
# demanding both keeps prose containing a bar from being read as a table.
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_DELIMITER_ROW = re.compile(r"^\s*\|(\s*:?-+:?\s*\|)+\s*$")

_FENCE = re.compile(r"^ {,3}(`{3,}|~{3,})(.*)$")


def _check_table(lines: list[str], start: int, end: int) -> list[Finding]:
    """
    Report each row of `lines[start:end]` whose cell count differs from the header's.

    Pandoc pads a short row and drops the cells past the header's count, so the
    text of an extra cell never reaches the output.
    """
    expected = len(split_pipe_table_row(lines[start]))
    findings: list[Finding] = []
    for offset in range(start, end):
        row = lines[offset]
        if _DELIMITER_ROW.match(row):
            continue
        count = len(split_pipe_table_row(row))
        if count != expected:
            findings.append(
                Finding(
                    offset + 1,
                    f"this row has {count} cells; the header row has {expected}",
                )
            )
    return findings


def _table_findings(lines: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    index = 0
    while index < len(lines):
        if not _TABLE_ROW.match(lines[index]):
            index += 1
            continue
        start = index
        while index < len(lines) and _TABLE_ROW.match(lines[index]):
            index += 1
        # A single pipe-delimited line is not a table -- GFM needs a delimiter row --
        # so there is no header to disagree with and nothing to say.
        if index - start >= 2:
            findings.extend(_check_table(lines, start, index))
    return findings


def _fence_findings(lines: list[str]) -> list[Finding]:
    """Report a fenced block that is never closed, at its opening line."""
    open_at: int | None = None
    fence = ""
    for offset, line in enumerate(lines):
        match = _FENCE.match(line)
        if not match:
            continue
        if open_at is None:
            # A backtick fence's info string may not contain a backtick, which is
            # what keeps an inline code span from opening a block here.
            if match.group(1)[0] == "`" and "`" in match.group(2):
                continue
            open_at, fence = offset, match.group(1)
        elif match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence):
            open_at = None
    if open_at is None:
        return []
    return [Finding(open_at + 1, f"fence `{fence}` is opened here and never closed")]


_NOT_MATH = re.compile(rf"`+[^`\n]*`+|\\\$|{DOLLAR_MATH}")


def _stray_dollars(lines: list[str], paragraph: list[int]) -> list[Finding]:
    """
    Lines of `paragraph` holding a `$` that pandoc reads as no math span.

    The paragraph is matched as a whole, because inline math may continue onto the
    next line. Code spans, escaped `\\$` and every span pandoc's rule (`DOLLAR_MATH`)
    reads as math are blanked first; a `$` left before a digit is currency.
    """
    text = "\n".join(lines[offset] for offset in paragraph)
    bare = _NOT_MATH.sub(lambda match: re.sub(r"[^\n]", " ", match.group(0)), text)
    stray = {
        paragraph[bare.count("\n", 0, match.start())]
        for match in re.finditer(r"\$(?!\d)", bare)
    }
    return [
        Finding(offset + 1, "unterminated `$` math delimiter on this line")
        for offset in sorted(stray)
    ]


def _math_findings(lines: list[str], fenced: frozenset[int]) -> list[Finding]:
    """
    Report a `$` that opens no math span pandoc would read.

    Lines inside a fenced code block are excluded. Display math legitimately spans
    lines, so a line that is exactly `$$` is a delimiter rather than an unterminated
    span.
    """
    findings: list[Finding] = []
    display_open = False
    paragraph: list[int] = []
    for offset, line in enumerate(lines):
        in_prose = not (offset in fenced or display_open or line.strip() in ("", "$$"))
        if in_prose:
            paragraph.append(offset)
            continue
        findings.extend(_stray_dollars(lines, paragraph))
        paragraph = []
        if offset not in fenced and line.strip() == "$$":
            display_open = not display_open
    findings.extend(_stray_dollars(lines, paragraph))
    if display_open:
        findings.append(Finding(len(lines), "unterminated `$$` display math"))
    return findings


def _fenced_line_numbers(lines: list[str]) -> frozenset[int]:
    """0-based indices of lines inside a fenced code block, delimiters included."""
    inside: set[int] = set()
    fence = ""
    for offset, line in enumerate(lines):
        match = _FENCE.match(line)
        if not fence:
            if match and not (match.group(1)[0] == "`" and "`" in match.group(2)):
                fence = match.group(1)
                inside.add(offset)
            continue
        inside.add(offset)
        if (
            match
            and match.group(1)[0] == fence[0]
            and len(match.group(1)) >= len(fence)
        ):
            fence = ""
    return frozenset(inside)


def preflight(text: str) -> list[Finding]:
    """
    Report constructs in `text` that pandoc probably reads differently than intended.

    Ordered by line. An empty list means nothing suspect was found -- which is not a
    claim that the document is well-formed, only that these checks had nothing to
    say about it.
    """
    lines = text.split("\n")
    fenced = _fenced_line_numbers(lines)
    findings = [
        *_table_findings(lines),
        *_fence_findings(lines),
        *_math_findings(lines, fenced),
    ]
    return sorted(findings, key=lambda finding: finding.line)
