"""Standalone Flowmark linter contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flowmark.lint import lint_text
from flowmark.lint_cli import main


def test_math_and_raw_tex_are_not_markdown_style_findings() -> None:
    source = (
        "Subscripts $x_i y_j$, \\(u_i v_j\\), and \\[a_i b_j\\] stay mathematical; "
        "so does \\underline{x_i} and \\mathcal{M}_{1}.\n"
    )
    assert lint_text(source) == []


def test_formatter_normalization_is_not_a_lint_diagnostic() -> None:
    assert lint_text("Use _emphasis_ and __strong__ here.\n") == []


def test_linter_does_not_invent_math_from_unparsed_dollar_text() -> None:
    # Pandoc does not produce a Math node for this source. A linter cannot call
    # it "unterminated math" without independently inventing author intent.
    assert lint_text("An unmatched $x_i expression.\n") == []


def test_multiline_pandoc_inline_math_is_not_reported_as_unterminated() -> None:
    # Regression from the Zettlr workspace. Pandoc's mathInlineWith explicitly
    # permits a single physical newline; the old preflight counted dollars per
    # line and emitted two contradictory "unterminated $" errors.
    source = (
        "summand of $B\\cong U\\oplus U\\oplus\\latI_{0,7}$; then "
        "$e^{\\perp B} = \\ZZ e\\oplus\n"
        "U\\oplus\\latI_{0,7}$ and "
        "$e^{\\perp}/e\\cong U\\oplus\\latI_{0,7}\\cong\\latI_{1,8}$,\n"
    )
    assert lint_text(source) == []


def test_json_cli_is_editor_consumable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "doc.md"
    path.write_text("[x]: /a\n[x]: /b\n\n[x][]\n")
    assert main(["--format", "json", "--exit-zero", str(path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == 1
    assert payload["files"][0]["path"] == str(path)
    diagnostic = next(
        item
        for item in payload["files"][0]["diagnostics"]
        if item["rule"] == "reference/duplicate-definition"
    )
    assert diagnostic["rule"] == "reference/duplicate-definition"
    assert diagnostic["line"] == 2
    assert diagnostic["column"] == 1


def test_json_cli_uses_source_path_for_stdin_local_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source_path = tmp_path / "source.md"
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("[missing](nope.md)\n"))
    assert (
        main(
            ["--format", "json", "--exit-zero", "--source-path", str(source_path), "-"]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    rules = {item["rule"] for item in payload["files"][0]["diagnostics"]}
    assert "link/missing-local-target" in rules


def test_cli_style_switches_enable_opt_in_rules(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "doc.md"
    path.write_text("https://example.com\n")
    assert (
        main(["--format", "json", "--exit-zero", "--style", "bare-url", str(path)]) == 0
    )
    payload = json.loads(capsys.readouterr().out)
    rules = {item["rule"] for item in payload["files"][0]["diagnostics"]}
    assert "style/bare-url" in rules
