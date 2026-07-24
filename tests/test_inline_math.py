"""Test inline math preservation."""

from flowmark.formats.flowmark_markdown import flowmark_markdown
from flowmark.linewrapping.markdown_filling import fill_markdown
from flowmark.reformat_api import reformat_text


def test_inline_math_preserves_latex_subscripts_verbatim():
    """Inline math must not parse LaTeX underscores as Markdown emphasis."""
    md = flowmark_markdown()

    source = (
        "The generated semifan is "
        "$\\mathcal{F}_{\\mathrm{gen}} = \\bigcup_{h \\in H} h\\mathcal{F}$.\n"
        "The local forms are $L_{1, \\mathbf{Z}_p}$ and $L_{2, \\mathbf{Z}_p}$.\n"
        "The automorphism group is "
        "$Aut_{\\operatorname{Lat}}(L)$ and $G_\\beta \\subset GL_n$.\n"
    )

    result = md(source)

    assert result == source


def test_same_line_double_dollar_math_preserves_latex_subscripts_verbatim():
    """Same-line $$...$$ math must not parse LaTeX underscores as Markdown emphasis."""
    md = flowmark_markdown()

    source = "The characterization is $$ \\operatorname{GL}_n = G_\\beta $$.\n"

    result = md(source)

    assert result == source


# --- #17 part 2: an inline math span is atomic to the wrapper ----------------
#
# Wrapping could place a newline at a space *inside* `$...$`, which changes the
# math pandoc reads: `Math InlineMath "H^1(X,\\mathcal O_X)=0"` became
# `Math InlineMath "H^1(X,\\mathcal\nO_X)=0"`. LaTeX tolerates the newline, but
# the AST changes, so `--verify` correctly refused to write -- meaning any
# document with enough inline math was unformattable at the default width. The
# reporter's document hit this ~14 times.
#
# The span is only split when moving it wholesale would leave the previous line
# short, so this is a wrap-cost decision: "inside math" has to cost infinity.

MATH_WRAP_SOURCE = "word word word word word word word word word word word word word and $H^1(X,\\mathcal O_X)=0$ plus more trailing words here to force a wrap decision.\n"


def test_wrapping_never_breaks_inside_inline_math():
    """The #17 reproducer, at the default width."""
    result = fill_markdown(MATH_WRAP_SOURCE, dedent_input=False)

    assert "$H^1(X,\\mathcal O_X)=0$" in result, result
    for line in result.splitlines():
        assert line.count("$") % 2 == 0, f"a math span straddles a line break: {line!r}"


def test_wrapping_takes_a_short_line_rather_than_splitting_math():
    """
    Moving the whole span down is the correct trade, even when it leaves the
    previous line well short of the width. #17 notes flowmark already does the
    right thing when fewer leading words precede the span; the defect was only in
    the case where the cost function preferred the split.
    """
    result = fill_markdown(MATH_WRAP_SOURCE, dedent_input=False)
    first_line = result.splitlines()[0]

    assert "$" not in first_line, first_line


def test_verify_accepts_the_math_reproducer_at_the_default_width():
    """
    The user-facing consequence: the document formats with the gate on, rather
    than being unformattable.
    """
    reformat_text(MATH_WRAP_SOURCE, verify=True)
