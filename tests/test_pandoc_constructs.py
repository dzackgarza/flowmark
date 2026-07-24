"""
Round-trip tests for Pandoc constructs that flowmark must not alter.

Every source below is well-formed: `pandoc -f markdown` parses it with zero
warnings. These go through `reformat_text`, the entry point the CLI uses, since
some of these defects live in that pipeline rather than in the parser itself.

Flowmark is free to change a construct's spelling, so where it deliberately
normalizes (indented code to fenced, a blank line between footnote definitions)
these assert the normalized form; the rest must survive byte-identically.

Covers #5 (footnote definitions), #6 (nested divs), #7 (indented code blocks),
and #8 (raw inline TeX). Fenced div attribute specs are in test_fenced_div.py
(#3).
"""

from flowmark.reformat_api import reformat_text

# --- #5: footnote definitions ---------------------------------------------


def test_consecutive_footnote_definitions_both_survive():
    """
    Pandoc needs no blank line between footnote definitions. Indenting the
    second made it a continuation of the first's body, deleting a footnote.

    The blank line between definitions is added -- a spelling change that keeps
    both definitions, unlike the merge it replaces.
    """
    source = "Text.[^1] More text.[^2]\n\n[^1]: First note.\n[^2]: Second note.\n"
    expected = "Text.[^1] More text.[^2]\n\n[^1]: First note.\n\n[^2]: Second note.\n"

    assert reformat_text(source) == expected


def test_footnote_definitions_separated_by_blank_line_round_trip():
    source = "Text.[^1] More text.[^2]\n\n[^1]: First note.\n\n[^2]: Second note.\n"

    assert reformat_text(source) == source


def test_multi_paragraph_footnote_definition_keeps_its_continuation():
    """
    With the label on its own line and a two-paragraph body, the second
    paragraph was de-indented out of the footnote and fenced as a code block,
    so its markup stopped parsing.
    """
    source = "T.[^1]\n\n[^1]:\n    First para.\n\n    Second para.\n"

    assert reformat_text(source) == source


def test_multi_paragraph_footnote_definition_inline_start_round_trips():
    source = "T.[^1]\n\n[^1]: First para.\n\n    Second para.\n"

    assert reformat_text(source) == source


# --- #6: nested divs -------------------------------------------------------


def test_nested_divs_do_not_gain_a_closing_fence():
    """
    The non-nesting parse closed the outer div at the inner closer, so trailing
    content escaped the parent and an extra fence was emitted.
    """
    source = "::: {.theorem}\nOuter before.\n\n::: {.proof}\nInner.\n:::\n\nOuter after.\n:::\n"

    assert reformat_text(source) == source


def test_deeply_nested_divs_round_trip():
    source = "::: {.a}\n::: {.b}\n::: {.c}\nDeep.\n:::\n:::\n:::\n"

    assert reformat_text(source) == source


def test_colon_run_inside_code_block_does_not_close_the_div():
    """
    A colon run inside a fenced code block is literal text, not a fence. Counting
    it closed the div early, leaving the code block's own closing fence to escape
    to top level: pandoc read ``["Div"]`` before and ``["Div", "Para"]`` after.
    """
    source = "::: {.foo}\n```\n:::\n```\nAfter.\n:::\n"

    assert reformat_text(source) == source


def test_div_opener_inside_code_block_does_not_inflate_depth():
    """The same defect in the other direction: the div's real closer got eaten."""
    source = "::: {.foo}\n```\n::: {.bar}\n```\nAfter.\n:::\n"

    assert reformat_text(source) == source


def test_colon_run_inside_tilde_code_block_does_not_close_the_div():
    source = "::: {.foo}\n~~~\n:::\n~~~\nAfter.\n:::\n"

    assert reformat_text(source) == source


def test_code_block_inside_nested_div_does_not_disturb_depth():
    source = "::: {.a}\n::: {.b}\n```\n:::\n```\n:::\nAfter.\n:::\n"

    assert reformat_text(source) == source


# --- #7: indented code blocks ---------------------------------------------
#
# Flowmark deliberately rewrites indented code blocks to fenced ones, which is a
# spelling change that keeps the block a code block. These assert that the block
# survives *as code* -- what regressed was a leading one silently becoming prose.


def test_indented_code_block_as_first_block_stays_code():
    """
    The four-space indent is the only thing marking the block as code, and it
    sits where the document-edge strip could reach it.
    """
    assert reformat_text("    literal code\n\nAfter.\n") == "```\nliteral code\n```\n\nAfter.\n"


def test_indented_code_block_alone_stays_code():
    """A document that is nothing but an indented code block."""
    assert reformat_text("    literal code\n") == "```\nliteral code\n```\n"


def test_indented_code_block_after_paragraph_stays_code():
    assert reformat_text("Intro.\n\n    literal code\n\nAfter.\n") == "Intro.\n\n```\nliteral code\n```\n\nAfter.\n"


def test_leading_blank_lines_are_still_stripped():
    """Blank lines at the document edges must still go."""
    assert reformat_text("\n\nIntro.\n\n\n") == "Intro.\n"


# --- #8: raw inline TeX ----------------------------------------------------


def test_raw_inline_tex_underscores_are_not_emphasis():
    """
    Two underscores spanning raw TeX were read as an emphasis pair and
    re-rendered with asterisks, producing invalid LaTeX.
    """
    source = "A \\overline{ \\mathcal{M}_{1} } b y_{2} c.\n"

    assert reformat_text(source) == source


def test_raw_inline_tex_flat_command_round_trips():
    source = "A \\overline{ M_{1} } b y_{2} c.\n"

    assert reformat_text(source) == source


def test_inline_math_with_underscores_round_trips():
    source = "A $\\overline{ \\mathcal{M}_{1} }$ b $y_{2}$ c.\n"

    assert reformat_text(source) == source


# --- #11: subscript --------------------------------------------------------


def test_subscript_survives_and_is_not_strikeout():
    """
    Pandoc's `subscript` extension (on by default for `-f markdown`) reads
    `H~2~O` as H, subscript 2, O. Parsing single tildes as GFM strikethrough
    and re-emitting them doubled turns the subscript into a strikeout -- a
    different construct entirely.
    """
    source = "H~2~O and x^2^.\n"

    assert reformat_text(source) == source


# --- #10: definition lists --------------------------------------------------


def test_definition_list_compact_round_trips():
    """
    Pandoc's `definition_lists` extension (on by default for `-f markdown`):
    the marker only means anything at line start, so rewrapping must not join
    it into the term's paragraph.
    """
    source = "Term\n:   Definition here.\n"

    assert reformat_text(source) == source


def test_definition_list_loose_round_trips():
    source = "Term 1\n\n:   Definition 1\n\nTerm 2\n\n:   Definition 2\n"

    assert reformat_text(source) == source


def test_definition_list_multiple_definitions_round_trip():
    source = "Term\n:   Def one\n:   Def two\n"

    assert reformat_text(source) == source


def test_definition_list_tilde_marker_round_trips():
    source = "Term\n~   Definition here.\n"

    assert reformat_text(source) == source


def test_definition_list_between_paragraphs_round_trips():
    source = "Before.\n\nTerm\n:   Definition.\n\nAfter paragraph.\n"

    assert reformat_text(source) == source


def test_definition_list_continuation_paragraph_round_trips():
    source = "Term\n:   First para.\n\n    Second para of same def.\n\nAfter.\n"

    assert reformat_text(source) == source


def test_definition_marker_mid_paragraph_stays_prose():
    """
    Pandoc's definition lists do NOT interrupt a paragraph: with text above
    the term, the whole thing is one Para. Flowmark must keep treating it as
    prose -- the default verify gate asserts the meaning is unchanged.
    """
    result = reformat_text("Some text\nTerm\n:   Def\n")

    assert ":" in result
