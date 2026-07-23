"""
Cheap checks for input that was already ambiguous before flowmark touched it.

When verification fails there are two different questions: *did flowmark break
this?* and *was this already broken?*  The pandoc gate can only ask the first, so
it answered the second one wrong -- in #17 the reporter's pipe table held an
unescaped `|` from a linear system inside inline math, pandoc already mis-parsed
the row, and the gate reported a flowmark bug.  That cost a bisection to attribute.

So these run only when verification has already failed, and only to say "here is
something in your input that pandoc reads differently than you probably meant".
They never gate a run on their own and they never fire on a document that verified.

**Precision over recall.**  A check that fires on ordinary markdown would relabel
every real flowmark defect as the user's fault, which is worse than the message it
replaces.  Each check below is written to be quiet unless it is fairly sure, and
`test_preflight_is_quiet_on_clean_input` is what holds that line.  Missing a
malformed document costs today's message; a false positive costs the truth.

The same checks are importable on their own, so a document can be checked without
reformatting it -- problem 3 in #17 was breaking the reporter's pandoc build before
flowmark ever ran.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


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

# Inline math and code spans, for finding a bar *inside* one. Deliberately simple:
# this runs on a single table row, where the constructs cannot span lines.
_SPANS_IN_ROW = re.compile(r"\$[^$\n]+\$|`+[^`\n]+`+")

_FENCE = re.compile(r"^ {,3}(`{3,}|~{3,})(.*)$")


def _split_cells(row: str) -> list[str]:
    """
    The cells of a pipe-table row, as pandoc splits them: on every unescaped `|`.

    This is the naive split *on purpose*. Its disagreement with the author's intent
    is the defect being detected -- pandoc splits the same way, which is why the
    reporter's three logical cells became five.
    """
    inner = row.strip().strip("|")
    return re.split(r"(?<!\\)\|", inner)


def _check_table(lines: list[str], start: int, end: int) -> list[Finding]:
    """Check one run of consecutive table rows, `lines[start:end]`."""
    findings: list[Finding] = []
    expected = len(_split_cells(lines[start]))

    for offset in range(start, end):
        row = lines[offset]
        number = offset + 1

        for span in _SPANS_IN_ROW.finditer(row):
            if "|" in span.group(0):
                findings.append(
                    Finding(
                        number,
                        f"unescaped `|` inside {span.group(0)!r} in a pipe-table row; "
                        f"pandoc splits the row there, so this cell is read as two",
                    )
                )
                break

        if _DELIMITER_ROW.match(row):
            continue
        count = len(_split_cells(row))
        if count != expected and not any(f.line == number for f in findings):
            findings.append(
                Finding(
                    number,
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


def _math_findings(lines: list[str], fenced: frozenset[int]) -> list[Finding]:
    """
    Report a line with an odd number of `$` delimiters.

    Escaped `\\$` and lines inside a fenced code block are excluded, and so is a
    lone `$` that is plainly currency -- a digit right after it with no closer.
    Display math legitimately spans lines, so a line that is exactly `$$` is a
    delimiter rather than an unterminated span.
    """
    findings: list[Finding] = []
    display_open = False
    for offset, line in enumerate(lines):
        if offset in fenced:
            continue
        if line.strip() == "$$":
            display_open = not display_open
            continue
        if display_open:
            continue
        bare = re.sub(r"\\\$", "", re.sub(r"`+[^`\n]*`+", "", line))
        if bare.count("$") % 2 == 0:
            continue
        if re.fullmatch(r"[^$]*\$\d[^$]*", bare):
            continue  # a single price, not an opened span
        findings.append(Finding(offset + 1, "unterminated `$` math delimiter on this line"))
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
        if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence):
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
