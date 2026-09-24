"""
Whitespace inside an inline construct the parser read as one element.

The renderer writes such an element -- inline math, raw TeX, a code span, a link --
with its whitespace replaced by noncharacters. Every splitter downstream (words,
sentences, hard breaks) then sees one token, so no line or sentence break can land
inside it, and `restore_spaces` puts the whitespace back once the document is
rendered. What is unbreakable is decided by the parse, not re-derived from the
rendered text by pattern matching (#28).

A line ending inside the element is restored as a space: CommonMark and pandoc read
a line ending in a code span as a space, and TeX reads the end of a line as a space
(The TeXbook, chapter 8). A tab is kept a tab.

U+FDD0 and U+FDD1 are Unicode noncharacters. Noncharacters are permanently reserved
for a process's internal use and are not interchanged (The Unicode Standard, section
23.7 "Noncharacters"), so no document legitimately contains one; `refuse_if_present`
rejects one that does rather than corrupt it.
"""

from __future__ import annotations

_SPACE = "﷐"
_TAB = "﷑"

_HIDE = str.maketrans({" ": _SPACE, "\n": _SPACE, "\t": _TAB})
_RESTORE = str.maketrans({_SPACE: " ", _TAB: "\t"})


def unbreakable(text: str) -> str:
    """`text` with no whitespace a splitter could break at."""
    return text.translate(_HIDE)


def restore_spaces(text: str) -> str:
    """Undo `unbreakable`, with a hidden line ending coming back as a space."""
    return text.translate(_RESTORE)


def refuse_if_present(text: str) -> None:
    """Raise `ValueError` if `text` already contains a reserved noncharacter."""
    found = [text.index(char) for char in (_SPACE, _TAB) if char in text]
    if found:
        line = text.count("\n", 0, min(found)) + 1
        raise ValueError(
            f"line {line} contains a Unicode noncharacter (U+FDD0 or U+FDD1) that "
            "flowmark reserves for internal use; remove it before formatting"
        )
