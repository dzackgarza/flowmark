"""Standalone Pandoc-aware Markdown linting built on Flowmark's semantic parser.

The linter has one syntax authority: the same parser and normalizer Flowmark uses to
format Pandoc-flavoured Markdown.  It does not run a second Markdown grammar over the
source.  Consequently math, raw TeX, fenced divs, definition lists, tables, footnotes,
and the other constructs Flowmark models are opaque or structured in exactly the same
places during linting as they are during formatting.

Two rule families are reported:

* ``pandoc/ambiguous-input``: high-confidence constructs already detected by
  :func:`flowmark.preflight.preflight` as likely to be read by Pandoc differently from
  what the author intended.
* ``format/canonical``: source ranges whose spelling differs from Flowmark's canonical
  rendering under the requested formatting policy.  This is a semantic normalization
  check, not a regex style checker: the source is parsed before it is rendered.

The public result is editor-neutral.  A CLI, an editor, CI, or a pre-commit hook can all
consume the same diagnostics without importing CodeMirror or any Zettlr code.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from enum import StrEnum

from flowmark.formats.flowmark_markdown import ListSpacing
from flowmark.preflight import preflight
from flowmark.reformat_api import reformat_text


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
    """Formatting policy used by the canonical-form rule.

    Defaults deliberately avoid prose reflow and opinionated typography.  They model
    the structural/style checks an editor expects: Flowmark may normalize Markdown
    syntax, but ordinary paragraph line breaking, quotes, ellipses, and list tightness
    are left alone unless the caller explicitly opts in.
    """

    width: int = 0
    semantic: bool = False
    cleanups: bool = False
    smartquotes: bool = False
    ellipses: bool = False
    list_spacing: ListSpacing = ListSpacing.preserve
    check_format: bool = True


def _line_end_column(lines: list[str], line: int) -> int:
    """Return the 1-based column immediately after ``line``'s visible text."""
    if not lines:
        return 1
    index = min(max(line - 1, 0), len(lines) - 1)
    return len(lines[index].rstrip("\n")) + 1


def _format_diagnostics(source: str, normalized: str) -> list[LintDiagnostic]:
    """Convert a line diff against canonical output into source diagnostics."""
    if source == normalized:
        return []

    source_lines = source.splitlines(keepends=True)
    normalized_lines = normalized.splitlines(keepends=True)
    # splitlines() returns [] for an empty document.  The synthetic line keeps
    # insertion diagnostics representable at line 1 without special coordinates.
    coordinate_lines = source_lines or [""]
    matcher = SequenceMatcher(a=source_lines, b=normalized_lines, autojunk=False)
    diagnostics: list[LintDiagnostic] = []

    for (
        tag,
        source_start,
        source_end,
        normalized_start,
        normalized_end,
    ) in matcher.get_opcodes():
        if tag == "equal":
            continue

        first_line = min(source_start + 1, len(coordinate_lines))
        if source_end > source_start:
            last_line = min(source_end, len(coordinate_lines))
        else:
            last_line = first_line
        replacement = "".join(normalized_lines[normalized_start:normalized_end])

        diagnostics.append(
            LintDiagnostic(
                rule="format/canonical",
                severity=Severity.WARNING,
                message="Markdown differs from Flowmark's canonical Pandoc-aware form.",
                line=first_line,
                column=1,
                end_line=last_line,
                end_column=_line_end_column(coordinate_lines, last_line),
                replacement=replacement,
            )
        )

    return diagnostics


def lint_text(text: str, options: LintOptions | None = None) -> list[LintDiagnostic]:
    """Lint one Markdown document without modifying it.

    Ambiguous-input findings are returned first.  If they exist, canonical-format
    diagnostics are withheld: formatting malformed or semantically ambiguous input can
    produce secondary spelling differences that are less useful than the root defect.
    """
    if options is None:
        options = LintOptions()

    ambiguous = [
        LintDiagnostic(
            rule="pandoc/ambiguous-input",
            severity=Severity.ERROR,
            message=finding.message,
            line=finding.line,
            column=1,
            end_line=finding.line,
            end_column=_line_end_column(
                text.splitlines(keepends=True) or [""], finding.line
            ),
        )
        for finding in preflight(text)
    ]
    if ambiguous or not options.check_format:
        return ambiguous

    normalized = reformat_text(
        text,
        width=options.width,
        plaintext=False,
        semantic=options.semantic,
        cleanups=options.cleanups,
        smartquotes=options.smartquotes,
        ellipses=options.ellipses,
        list_spacing=options.list_spacing,
        verify=False,
    )
    return _format_diagnostics(text, normalized)


__all__ = ("LintDiagnostic", "LintOptions", "Severity", "lint_text")
