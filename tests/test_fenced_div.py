"""
Test Pandoc fenced div handling (``::: {.attrs}`` ... ``:::``).

Pandoc's grammar for the opening fence is: three or more colons, then the
whole remainder of the line is the div's attribute specification -- either a
braced block (``{#id .class key="val"}``) or a bare class word (``::: proof``).
There is no "trailing content on the same line": pandoc rejects
``::: {.foo} text`` as a div entirely, so no part of the opening line may ever
be re-emitted as div body content.

https://pandoc.org/MANUAL.html#divs-and-spans
"""

from flowmark.formats.flowmark_markdown import flowmark_markdown


def test_fenced_div_braced_attrs_round_trip():
    """A canonical braced attribute block is preserved verbatim."""
    md = flowmark_markdown()

    source = "::: {.foo}\nBody.\n:::\n"

    assert md(source) == source


def test_fenced_div_brace_in_quoted_value_stays_on_opening_fence():
    """
    A ``}`` inside a quoted attribute value must not terminate the attribute
    block.  Regression: the attribute regex used ``\\{[^}]*\\}``, which stopped
    at the first ``}`` -- including one inside ``title="{...}"`` -- and pushed
    the remainder onto the next line, corrupting the title in the parsed AST.
    """
    md = flowmark_markdown()

    source = (
        '::: {#thm:main-identification .theorem title="{[@AEGS23, Thm. 1.1]}"}\n'
        "Let $F$ be the moduli space.\n"
        ":::\n"
    )

    assert md(source) == source


def test_fenced_div_brace_mid_quoted_value_stays_on_opening_fence():
    """A ``}`` in the middle of a quoted value must not split the fence line."""
    md = flowmark_markdown()

    source = '::: {#t .theorem title="a}b"}\nBody.\n:::\n'

    assert md(source) == source


def test_fenced_div_escaped_quotes_in_value_stay_on_opening_fence():
    """A quoted value may contain escaped quotes around a brace."""
    md = flowmark_markdown()

    source = '::: {#t data="{\\"k\\": 1}"}\nBody.\n:::\n'

    assert md(source) == source


def test_fenced_div_bare_class_round_trip():
    """
    ``::: proof`` is pandoc's bare-class shorthand for ``::: {.proof}``.
    Regression: the bare word was treated as trailing content and emitted as
    body text, which stopped the block from parsing as a Div at all.
    """
    md = flowmark_markdown()

    source = "::: proof\nBody.\n:::\n"

    assert md(source) == source


def test_fenced_div_long_fence_round_trip():
    """Pandoc allows any opening fence of three or more colons."""
    md = flowmark_markdown()

    source = ":::::::: proof\nBody.\n::::::::\n"

    assert md(source) == source


def test_fenced_div_long_fence_with_short_closer_round_trip():
    """Pandoc accepts a closing fence shorter than the opening fence."""
    md = flowmark_markdown()

    source = ":::::::::::::::: proof\nBody.\n:::\n"

    assert md(source) == source


def test_fenced_div_no_attrs_round_trip():
    """A bare ``:::`` fence with no attribute spec is preserved."""
    md = flowmark_markdown()

    source = ":::\nBody.\n:::\n"

    assert md(source) == source


def test_fenced_div_attr_block_without_space_is_normalized():
    """
    ``:::{.foo}`` is normalized to pandoc's canonical ``::: {.foo}`` spacing.
    This is a rendering choice, not a parse change: both forms carry the same
    attributes, so the parsed AST is unaffected.
    """
    md = flowmark_markdown()

    assert md(":::{.foo}\nBody.\n:::\n") == "::: {.foo}\nBody.\n:::\n"


def test_fenced_div_body_is_preserved_verbatim():
    """
    Div bodies are preserved verbatim (the documented contract), so nothing on
    the opening fence line may leak into them and nothing in them is reflowed.
    """
    md = flowmark_markdown()

    source = "::: {.foo}\nFirst sentence. Second sentence.\n:::\n"

    assert md(source) == source
