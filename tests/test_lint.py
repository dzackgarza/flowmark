"""Standalone Flowmark linter contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flowmark.lint import LintOptions, Severity, lint_text
from flowmark.lint_cli import main


def test_math_and_raw_tex_are_not_markdown_style_findings() -> None:
    source = (
        "Subscripts $x_i y_j$, \\(u_i v_j\\), and \\[a_i b_j\\] stay mathematical; "
        "so does \\underline{x_i} and \\mathcal{M}_{1}.\n"
    )
    assert lint_text(source) == []


def test_genuine_markdown_emphasis_is_normalized_semantically() -> None:
    diagnostics = lint_text("Use _emphasis_ and __strong__ here.\n")
    assert diagnostics
    assert all(d.rule == "format/canonical" for d in diagnostics)
    replacement = "".join(d.replacement or "" for d in diagnostics)
    assert "*emphasis*" in replacement
    assert "**strong**" in replacement


def test_preflight_ambiguity_wins_over_secondary_formatting() -> None:
    diagnostics = lint_text("An unterminated $x_i expression.\n")
    assert len(diagnostics) == 1
    assert diagnostics[0].rule == "pandoc/ambiguous-input"
    assert diagnostics[0].severity is Severity.ERROR


def test_format_check_can_be_disabled() -> None:
    assert lint_text("Use _emphasis_ here.\n", LintOptions(check_format=False)) == []


def test_json_cli_is_editor_consumable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "doc.md"
    path.write_text("Use _emphasis_ here.\n")
    assert main(["--format", "json", "--exit-zero", str(path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == 1
    assert payload["files"][0]["path"] == str(path)
    diagnostic = payload["files"][0]["diagnostics"][0]
    assert diagnostic["rule"] == "format/canonical"
    assert diagnostic["line"] == 1
    assert diagnostic["column"] == 1
