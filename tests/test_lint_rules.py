"""Coverage for Flowmark's explicit Pandoc-aware lint rule layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from flowmark.lint import LintOptions, StyleRule, lint_text


def rule_ids(text: str, *, options: LintOptions | None = None, source_path: Path | None = None) -> set[str]:
    return {diagnostic.rule for diagnostic in lint_text(text, options, source_path=source_path)}


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("# H1\n\n### H3\n", "heading/increment"),
        ("## Same\n\nText\n\n## Same\n", "heading/duplicate"),
        ("# A\n\n# B\n", "heading/multiple-h1"),
        ("#Heading\n", "heading/malformed"),
        ("####### Heading\n", "heading/malformed"),
        ("[text][missing]\n", "reference/undefined"),
        ("[unused]: /target\n", "reference/unused-definition"),
        ("[x]: /a\n[x]: /b\n\n[x][]\n", "reference/duplicate-definition"),
        ("[text]()\n", "link/empty-destination"),
        ("(text)[https://example.com]\n", "link/reversed-syntax"),
        ("[text](https://example.com]\n", "link/malformed-syntax"),
        ("[ text ](https://example.com)\n", "link/text-padding"),
        ("Use * text * here.\n", "emphasis/padding"),
        ("![](image.png)\n", "accessibility/image-alt"),
        ("[click here](https://example.com)\n", "link/non-descriptive-text"),
        ("# Heading\n\n[bad](#missing)\n", "link/invalid-fragment"),
        ("Text[^missing].\n", "footnote/undefined"),
        ("[^unused]: note\n", "footnote/unused-definition"),
        ("Text[^x].\n\n[^x]: one\n[^x]: two\n", "footnote/duplicate-definition"),
        ("---\ntitle: A\ntitle: B\n---\n\nText\n", "frontmatter/duplicate-key"),
        ("---\ntitle: [oops\n---\n\nText\n", "frontmatter/malformed-flow"),
        ("---\ntitle: A\n", "frontmatter/unclosed"),
        ("```\ncode\n```\n", "code/missing-language"),
        ("```python\ncode\n", "code/unclosed-fence"),
        ("```python\n\tx=1\n```\n", "code/hard-tab"),
        ("Text\n```python\nx=1\n```\nAfter\n", "code/surrounding-blank-lines"),
        (
            "Text\n| a | b |\n| --- | --- |\n| x | y |\nAfter\n",
            "table/surrounding-blank-lines",
        ),
        ("# A {#x}\n\n# B {#x}\n", "pandoc/duplicate-identifier"),
        ("# A {#x .foo\n", "pandoc/malformed-attributes"),
        ("::: theorem\nText\n", "pandoc/unclosed-fenced-div"),
        ("\\begin{align}\nx &= y\n", "tex/unclosed-environment"),
        (
            "\\begin{align}\nx &= y\n\\end{equation}\n",
            "tex/mismatched-environment",
        ),
        ("\\end{align}\n", "tex/unmatched-environment-end"),
        ("\\[\nx_i\n", "math/unclosed-display"),
        ("Inline \\(x_i with no closer.\n", "math/unclosed-inline"),
        ("Inline $x_i_j$.\n", "math/repeated-subscript"),
        ("Inline $x^2^3$.\n", "math/repeated-superscript"),
        ("Inline $x_{i$.\n", "math/unclosed-group"),
        ("Inline $x_i}$.\n", "math/unmatched-group-close"),
        ("Inline $\\left(x$.\n", "math/unclosed-left"),
        ("Inline $x\\right)$.\n", "math/unmatched-right"),
        ("Inline $Hom_R(M,N)$.\n", "math/bare-operator"),
        ("$$\nSpec R \\to Proj S\n$$\n", "math/bare-operator"),
    ],
)
def test_default_rules_cover_common_structural_and_semantic_failures(source: str, expected: str) -> None:
    assert expected in rule_ids(source)


def test_semantic_diagnostics_do_not_depend_on_formatter_spelling() -> None:
    diagnostics = lint_text("Use _emphasis_.\n\n[text][missing]\n")
    assert {d.rule for d in diagnostics} == {"reference/undefined"}


def test_math_code_and_raw_tex_are_opaque_to_markdown_rules() -> None:
    source = "Math $[x][missing] * text * x_i$, \\(y_j [bad](url]\\), and \\underline{z_k}.\n\n```text\n#Heading\n[text][missing]\nhttps://example.com\n```\n"
    diagnostics = lint_text(
        source,
        LintOptions(styles=frozenset({StyleRule.BARE_URL})),
    )
    assert diagnostics == []


def test_semantic_math_macros_and_braced_scripts_are_quiet() -> None:
    source = (
        r"$x_{i_j}, x_i^j, \Hom_R(M,N), \operatorname{Spec} R, \sin x$"
        "\n"
        r"\[ \mathrm{Hom}(M,N) \to \operatorname{Proj}(S) \]"
        "\n"
    )
    rules = rule_ids(source)
    assert "math/repeated-subscript" not in rules
    assert "math/repeated-superscript" not in rules
    assert "math/bare-operator" not in rules


def test_escaped_braces_and_tex_comments_do_not_corrupt_math_group_balance() -> None:
    source = "$\\left\\{ x_{i} \\right\\}$\n\n$$\nx_{i} % a comment with unmatched } and \\right\n+ y_{j}\n$$\n"
    rules = rule_ids(source)
    assert not any(
        rule
        in {
            "math/unclosed-group",
            "math/unmatched-group-close",
            "math/unclosed-left",
            "math/unmatched-right",
        }
        for rule in rules
    )


def test_tex_and_math_examples_inside_code_fences_are_literal() -> None:
    source = "```tex\n\\begin{align}\n$x_i_j = Hom(M,N)$\n\\end{equation}\n```\n"
    rules = rule_ids(source)
    assert "tex/mismatched-environment" not in rules
    assert "math/repeated-subscript" not in rules
    assert "math/bare-operator" not in rules


def test_valid_reference_footnote_fragment_and_image_are_quiet() -> None:
    source = (
        "# Target Heading\n\n[reference][ref] and [fragment](#target-heading) and ![diagram](image.png).\n\nText[^note].\n\n[ref]: https://example.com\n[^note]: Footnote.\n"
    )
    assert lint_text(source) == []


def test_local_file_and_cross_file_fragment_validation(tmp_path: Path) -> None:
    source_path = tmp_path / "source.md"
    target = tmp_path / "target.md"
    target.write_text("# Existing Heading\n")
    source = "[ok](target.md#existing-heading) [missing](absent.md) [bad-fragment](target.md#missing-heading)\n"
    rules = rule_ids(source, source_path=source_path)
    assert "link/missing-local-target" in rules
    assert "link/invalid-fragment" in rules


def test_opt_in_style_rules_are_not_default_policy() -> None:
    source = "* one\n+ two\n\n~~~python\nx=1\n~~~\n\n```python\ny=2\n```\n\nhttps://example.com\n\n## Heading.\n\n<span>html</span>\n"
    default_rules = rule_ids(source)
    assert not any(rule.startswith("style/") for rule in default_rules)

    options = LintOptions(
        styles=frozenset(
            {
                StyleRule.UNORDERED_LIST_MARKER,
                StyleRule.FENCE_MARKER,
                StyleRule.BARE_URL,
                StyleRule.HEADING_PUNCTUATION,
                StyleRule.REQUIRE_H1,
                StyleRule.NO_INLINE_HTML,
            }
        )
    )
    styled = rule_ids(source, options=options)
    assert {
        "style/unordered-list-marker",
        "style/fence-marker",
        "style/bare-url",
        "style/heading-punctuation",
        "style/required-h1",
        "style/no-inline-html",
    } <= styled


def test_line_length_is_an_explicit_policy_and_skips_code() -> None:
    source = "ordinary line that is definitely long\n\n```text\nthis code line is also definitely long\n```\n"
    diagnostics = lint_text(source, LintOptions(max_line_length=20))
    line_length = [d for d in diagnostics if d.rule == "style/line-length"]
    assert [d.line for d in line_length] == [1]


def test_reference_labels_are_case_and_whitespace_normalized() -> None:
    source = "[use][Some   Label]\n\n[some label]: /target\n"
    rules = rule_ids(source)
    assert "reference/undefined" not in rules
    assert "reference/unused-definition" not in rules


def test_duplicate_ids_inside_math_or_code_are_not_pandoc_attribute_ids() -> None:
    source = "$\\{#same\\}$\n\n```text\n{#same}\n{#same}\n```\n"
    assert "pandoc/duplicate-identifier" not in rule_ids(source)


def test_missing_pandoc_frontmatter_resources_are_path_aware(tmp_path: Path) -> None:
    source_path = tmp_path / "paper.md"
    (tmp_path / "refs.bib").write_text("@book{ok, title={OK}}\n")
    (tmp_path / "second.bib").write_text("@book{second, title={Second}}\n")
    source = (
        "---\n"
        "bibliography: [refs.bib, missing-inline.bib]\n"
        "include-in-header:\n"
        "  - second.bib\n"
        "  - headers/missing.tex\n"
        "csl: styles/missing.csl\n"
        "template: named-template\n"
        "---\n\n"
        "Text.\n"
    )
    diagnostics = lint_text(source, source_path=source_path)
    missing = [d for d in diagnostics if d.rule == "pandoc/missing-resource"]
    assert len(missing) == 3
    assert any("missing-inline.bib" in d.message for d in missing)
    assert any("headers/missing.tex" in d.message for d in missing)
    assert any("styles/missing.csl" in d.message for d in missing)
    assert not any("refs.bib" in d.message for d in diagnostics)
    assert not any("second.bib" in d.message for d in diagnostics)
    assert not any("named-template" in d.message for d in diagnostics)
