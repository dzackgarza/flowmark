"""Standalone Pandoc-aware Markdown linting with Pandoc as syntax authority.

Every lint pass first invokes the canonical Pandoc reader dialect.  Correctness rules
receive that exact JSON AST and warning stream; source scanners may locate an
already-proven node but may not independently decide that Markdown syntax exists.

The reported rules are explicit semantic/structural checks (references, headings,
links, footnotes, frontmatter, Pandoc attributes, code fences, and TeX checks inside
math which the Pandoc grammar actually recognizes). The formatter's historical
``preflight`` heuristics are deliberately not lint rules: they guess author intent
from source spelling and do not have source-backed Pandoc grammar semantics.

Formatting is deliberately not a lint concern.  Whether source text differs from
Flowmark's canonical rendering is answered by the formatter/check surface, not by
editor diagnostics.  A linter finding therefore always identifies something that
requires author judgment or cannot be repaired uniquely by normalization.

Optional house-style policies are selected with :class:`StyleRule`; they are separate
from the default correctness rules so valid Pandoc Markdown is not rejected merely for
being written in another conventional style.

The public result is editor-neutral.  A CLI, an editor, CI, or a pre-commit hook can all
consume the same diagnostics without importing CodeMirror or any Zettlr code.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path

from flowmark.lint_rules import StyleRule, lint_rule_findings
from flowmark.pandoc_lint import (
    PandocJson,
    PandocLintUnavailableError,
    PandocMessage,
    parse_pandoc_for_lint,
)


class Severity(StrEnum):
    """Severity levels emitted by Flowmark's linter."""

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class LintDiagnostic:
    """One source diagnostic using 1-based line/column coordinates."""

    rule: str
    severity: Severity
    message: str
    line: int
    column: int
    end_line: int
    end_column: int
    replacement: str | None = None

    def to_json(self) -> dict[str, object]:
        """Return the stable JSON representation consumed by editor clients."""
        result = asdict(self)
        result["severity"] = self.severity.value
        return result


@dataclass(frozen=True)
class LintOptions:
    """Semantic lint policy.

    Formatting options intentionally do not exist here.  Flowmark's formatter owns
    normalization; the linter owns correctness, ambiguity, and explicitly requested
    authoring policies.
    """

    styles: frozenset[StyleRule] = field(default_factory=frozenset)
    max_line_length: int | None = None


def _offset_to_point(text: str, offset: int) -> tuple[int, int]:
    """Convert a source offset to a 1-based ``(line, column)`` pair."""
    offset = min(max(offset, 0), len(text))
    line = text.count("\n", 0, offset) + 1
    last_newline = text.rfind("\n", 0, offset)
    column = offset - last_newline
    return line, column


def _explicit_rule_diagnostics(
    text: str,
    options: LintOptions,
    source_path: Path | None,
    pandoc_document: dict[str, PandocJson],
) -> list[LintDiagnostic]:
    diagnostics: list[LintDiagnostic] = []
    for finding in lint_rule_findings(
        text,
        source_path=source_path,
        styles=options.styles,
        max_line_length=options.max_line_length,
        pandoc_document=pandoc_document,
    ):
        line, column = _offset_to_point(text, finding.start)
        end_line, end_column = _offset_to_point(text, finding.end)
        diagnostics.append(
            LintDiagnostic(
                rule=finding.rule,
                severity=Severity(finding.severity),
                message=finding.message,
                line=line,
                column=column,
                end_line=end_line,
                end_column=end_column,
                replacement=finding.replacement,
            )
        )
    return diagnostics


def _pandoc_message_rule(message: PandocMessage) -> str:
    lowered = message.message.casefold()
    if "error parsing yaml metadata" in lowered or "yaml parse exception" in lowered:
        return "frontmatter/malformed-flow"
    if "duplicate key" in lowered:
        return "frontmatter/duplicate-key"
    if "duplicate link reference" in lowered:
        return "reference/duplicate-definition"
    if "duplicate note reference" in lowered:
        return "footnote/duplicate-definition"
    if "note with key" in lowered and "not used" in lowered:
        return "footnote/unused-definition"
    if "div at line" in lowered and "unclosed" in lowered:
        return "pandoc/unclosed-fenced-div"
    return "pandoc/parse-error" if message.severity == "error" else "pandoc/warning"


def _pandoc_message_diagnostic(text: str, message: PandocMessage) -> LintDiagnostic:
    line = message.line or 1
    column = message.column or 1
    lines = text.splitlines() or [""]
    line_index = max(0, min(len(lines) - 1, line - 1))
    end_column = min(len(lines[line_index]) + 1, column + 1)
    return LintDiagnostic(
        rule=_pandoc_message_rule(message),
        severity=Severity.ERROR if message.severity == "error" else Severity.WARNING,
        message=message.message,
        line=line,
        column=column,
        end_line=line,
        end_column=end_column,
    )


def lint_text(
    text: str,
    options: LintOptions | None = None,
    *,
    source_path: Path | None = None,
) -> list[LintDiagnostic]:
    """Lint one Markdown document without modifying or normalizing it."""
    if options is None:
        options = LintOptions()

    try:
        pandoc = parse_pandoc_for_lint(text)
    except PandocLintUnavailableError as error:
        raise RuntimeError(str(error)) from error

    diagnostics = [
        _pandoc_message_diagnostic(text, message) for message in pandoc.messages
    ]
    if pandoc.document is not None:
        # The recursive JSON type is intentionally erased at this call boundary;
        # lint_rules treats it structurally through the pandoc_lint helpers.
        diagnostics.extend(
            _explicit_rule_diagnostics(
                text,
                options,
                source_path,
                pandoc.document,
            )
        )
    diagnostics.sort(key=lambda item: (item.line, item.column, item.rule))
    return diagnostics


__all__ = ("LintDiagnostic", "LintOptions", "Severity", "StyleRule", "lint_text")
