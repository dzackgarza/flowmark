"""Test inline math preservation."""

from flowmark.formats.flowmark_markdown import flowmark_markdown


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
