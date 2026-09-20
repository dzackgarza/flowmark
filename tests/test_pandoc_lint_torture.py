"""Adversarial linter corpus with the real Pandoc reader as the syntax oracle."""

from __future__ import annotations

import shutil

import pytest

from flowmark.lint import lint_text
from flowmark.pandoc_lint import parse_pandoc_for_lint


pandocless = pytest.mark.skipif(
    shutil.which("pandoc") is None, reason="requires the Pandoc oracle on PATH"
)


PROSE_LOOKALIKES = (
    "#Heading",
    "(text)[https://example.com]",
    "[text](https://example.com]",
    "Use * text * here.",
    "Text {#same} and more {#same}.",
    "[text][missing]",
    "Text[^missing].",
    "---\ntitle: A",
    "```python\ncode",
    "\\begin{align}\nx &= y",
    "\\begin{figure}\nx\n\\end{table}",
    "Inline $x_i with no closer.",
    "Inline \\(x_i with no closer.",
    "\\[\nx_i",
)


BOUNDARY_LOOKALIKES = (
    "Text\n## not-a-header-here",
    "Text\n| a | b |\n|---|---|\n| c | d |",
    "Text\n::: theorem\nbody\n:::",
    "Text\n---\ncontinuation",
)


@pandocless
def test_default_linter_is_quiet_on_pandoc_prose_lookalikes() -> None:
    # These are intentionally parser-looking strings.  The test first asserts
    # the canonical Pandoc reader accepts them without warnings/errors, then
    # requires the linter not to manufacture failed syntax from their spelling.
    for source in (*PROSE_LOOKALIKES, *BOUNDARY_LOOKALIKES):
        parsed = parse_pandoc_for_lint(source + "\n")
        assert parsed.parsed, source
        assert parsed.messages == (), source
        assert lint_text(source + "\n") == [], source


@pandocless
def test_parser_looking_source_inside_literal_regions_cannot_leak_lint_syntax() -> None:
    tokens = [
        "#Heading",
        "[text][missing]",
        "Text[^missing]",
        "{#same} {#same}",
        "\\begin{align}",
        "$unterminated",
        "::: theorem",
    ]
    documents: list[str] = []
    for token in tokens:
        documents.extend(
            [
                f"`{token}`\n",
                f"```text\n{token}\n```\n",
                f"\\begin{{figure}}\n{token}\n\\end{{figure}}\n",
            ]
        )
    documents.append(
        r"$\text{#Heading [text][missing] Text[^missing] {#same} ::: theorem} + x$"
        "\n"
    )

    for source in documents:
        parsed = parse_pandoc_for_lint(source)
        assert parsed.parsed, source
        assert not any(message.severity == "error" for message in parsed.messages), source
        rules = {diagnostic.rule for diagnostic in lint_text(source)}
        assert not any(
            rule.startswith(
                (
                    "heading/malformed",
                    "reference/undefined",
                    "footnote/undefined",
                    "math/unclosed-",
                    "tex/unclosed-",
                    "pandoc/duplicate-identifier",
                    "pandoc/unclosed-fenced-div",
                )
            )
            for rule in rules
        ), (source, rules)


@pytest.mark.parametrize(
    ("source", "warning_fragment", "rule"),
    [
        (
            "[x]: /a\n[x]: /b\n\n[x][]\n",
            "Duplicate link reference",
            "reference/duplicate-definition",
        ),
        (
            "Text[^x].\n\n[^x]: one\n[^x]: two\n",
            "Duplicate note reference",
            "footnote/duplicate-definition",
        ),
        (
            "[^unused]: note\n",
            "not used",
            "footnote/unused-definition",
        ),
        (
            "---\ntitle: A\ntitle: B\n---\n\nText\n",
            "Duplicate key",
            "frontmatter/duplicate-key",
        ),
        (
            "::: theorem\nText\n",
            "unclosed",
            "pandoc/unclosed-fenced-div",
        ),
    ],
)
@pandocless
def test_pandoc_warnings_are_mapped_without_reimplementing_the_grammar(
    source: str,
    warning_fragment: str,
    rule: str,
) -> None:
    parsed = parse_pandoc_for_lint(source)
    assert parsed.parsed
    assert any(warning_fragment.casefold() in item.message.casefold() for item in parsed.messages)
    assert rule in {diagnostic.rule for diagnostic in lint_text(source)}


@pandocless
def test_pandoc_parse_error_is_the_syntax_error() -> None:
    source = "---\ntitle: [oops\n---\n\nText\n"
    parsed = parse_pandoc_for_lint(source)
    assert not parsed.parsed
    assert any(item.severity == "error" for item in parsed.messages)
    diagnostics = lint_text(source)
    assert [item.rule for item in diagnostics] == ["frontmatter/malformed-flow"]


@pandocless
def test_atx_heading_level_is_pandoc_unbounded_not_commonmark_six() -> None:
    source = "####### Seven\n\n######## Eight\n"
    parsed = parse_pandoc_for_lint(source)
    assert parsed.parsed
    assert lint_text(source) == []
