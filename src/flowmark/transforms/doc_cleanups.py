from __future__ import annotations

from typing import cast

from marko import block, inline
from marko.block import Document
from marko.element import Element

from flowmark.transforms.doc_transforms import transform_tree


def _unbold_heading_transformer(element: Element) -> None:
    """
    Transformer function to unbold headings where the entire text is bold.
    """
    if isinstance(element, block.Heading):
        # Check if the heading consists *only* of a single StrongEmphasis element
        if len(element.children) == 1 and isinstance(element.children[0], inline.StrongEmphasis):
            # Replace the heading's children with the children of the StrongEmphasis element
            strong_emphasis_node = element.children[0]
            # marko types `children` as `str | Sequence[Element]`; assign dynamically
            # (StrongEmphasis children are Elements) rather than via a suppression comment.
            setattr(element, "children", strong_emphasis_node.children)

        # Handle the case where the heading is bold and italic (StrongEmphasis inside Emphasis or vice versa)
        # ***text***  -> *text*
        elif len(element.children) == 1 and isinstance(element.children[0], inline.Emphasis):
            emphasis_node = element.children[0]
            if len(emphasis_node.children) == 1 and isinstance(emphasis_node.children[0], inline.StrongEmphasis):
                strong_node = emphasis_node.children[0]
                emphasis_node.children = strong_node.children


def unbold_headings(doc: Document) -> None:
    """
    Find headings where the entire text is bold and remove the bold.

    Modifies the Marko document tree in place using a general transformer.
    Example: `## **My Heading**` -> `## My Heading`
    """
    transform_tree(doc, _unbold_heading_transformer)


# Suspended hyphenation: `the pre- and post-stable models` is a real construction,
# and joining it to `pre-and` corrupts the sentence. If a wrapper happened to break
# after the `pre-`, the following word is one of these, so they are excluded.
_SUSPENSION_WORDS = frozenset({"and", "or", "to", "nor", "but", "through", "versus"})


def _leading_text(element: Element) -> str:
    """
    The text a rendered element starts with, as far as this rule needs to know it.

    Inline math answers with its delimiter, which is all the rule asks: `degree-`
    followed by `$4$` joins, and the `$` is neither a suspension word nor a letter
    that could start one.
    """
    children = getattr(element, "children", None)
    if isinstance(children, str):
        return children
    if isinstance(children, list) and children:
        return _leading_text(cast("list[Element]", children)[0])
    return getattr(element, "delimiter", "") or ""


def _trailing_text(element: Element) -> str:
    """The text a rendered element ends with; the mirror of `_leading_text`."""
    children = getattr(element, "children", None)
    if isinstance(children, str):
        return children
    if isinstance(children, list) and children:
        return _trailing_text(cast("list[Element]", children)[-1])
    return ""


def _joins_across_break(before: Element, after: Element) -> bool:
    """
    Whether a soft break between these two siblings should close up.

    Narrow on purpose, per #18: the previous text must end in a hyphen, and the
    following token must begin with a digit, a lowercase letter, or inline math --
    never an uppercase word (which usually starts a new clause) and never a
    suspension conjunction.
    """
    if not _trailing_text(before).endswith("-"):
        return False
    following = _leading_text(after).lstrip()
    if not following:
        return False
    first_word = following.split()[0] if following.split() else ""
    if first_word.strip(".,;:!?").lower() in _SUSPENSION_WORDS:
        return False
    return following[0].isdigit() or following[0].islower() or following[0] in "$\\"


def _join_hyphen_breaks(element: Element) -> int:
    """
    Drop soft line breaks that fell immediately after a hyphen, in place.

    The `LineBreak` element is *removed* rather than its text edited, which is what
    makes the inline-math and inline-markup cases work: with the break gone,
    `degree-` and a following `CustomInlineMath` render adjacent as `degree-$4$`
    with no `Str`-level rule, and the same inside a `StrongEmphasis`.
    """
    joined = 0
    children = getattr(element, "children", None)
    if not isinstance(children, list):
        return 0

    kept: list[Element] = []
    items = cast("list[Element]", children)
    for index, child in enumerate(items):
        is_soft_break = isinstance(child, inline.LineBreak) and child.soft
        if is_soft_break and kept and index + 1 < len(items) and _joins_across_break(kept[-1], items[index + 1]):
            joined += 1
            continue
        kept.append(child)

    # `children` is not declared on marko's `Element` base (only on concrete
    # container subclasses), so assign it dynamically -- mirroring the `getattr`
    # read above -- rather than via a checker-suppression comment.
    setattr(element, "children", kept)
    for child in kept:
        joined += _join_hyphen_breaks(child)
    return joined


def join_hyphen_line_breaks(doc: Document) -> int:
    """
    Close up a line break that fell immediately after a hyphen, and say how many.

    The count is returned rather than swallowed because the rule is a heuristic and
    #18 says so plainly: the scope ("digit, lowercase, or inline math", minus the
    suspension conjunctions) will not be perfect, which argues for reporting rather
    than silence.
    """
    return _join_hyphen_breaks(doc)


def doc_cleanups(doc: Document) -> int:
    """
    Apply (ideally quite safe) cleanups to the document.

    Returns the number of hyphen line-joins performed, for reporting.
    """
    unbold_headings(doc)
    return join_hyphen_line_breaks(doc)
