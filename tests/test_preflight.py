"""
Tests for the ambiguous-input preflight.

When verification fails, the question "did flowmark break this?" and the question
"was this already broken?" have different answers and different owners. The gate
could only ever ask the first one, so it blamed flowmark for the second -- which in
#17 cost the reporter a bisection to attribute a defect that was in their input.

These are skipped without the pandoc binary where they need it, so contributors
without it are not blocked.
"""

import shutil

import pytest

from flowmark.pandoc_verify import MeaningChangedError
from flowmark.preflight import preflight
from flowmark.reformat_api import reformat_text

pandocless = pytest.mark.skipif(
    shutil.which("pandoc") is None, reason="requires the pandoc binary on PATH"
)


# The reporter's actual line from #17: an unescaped `|` from a linear system inside
# inline math, in a pipe-table row. Pandoc already mis-parses it -- the three logical
# cells read as five, and the citation is swallowed -- so reflowing the table shuffles
# the mis-split differently. Escaping the bars makes it verify clean on the first try.
AMBIGUOUS_TABLE = (
    "| col | status | ref |\n"
    "|---|---|---|\n"
    "| $|-2K_{\\widetilde V}|=\\{C\\}$ generically | established | @sec:anti-bicanonical |\n"
)


def test_preflight_finds_a_bar_inside_inline_math_in_a_table_row():
    findings = preflight(AMBIGUOUS_TABLE)

    assert findings, "the reporter's row must be found"
    assert findings[0].line == 3, "the row is named at its own line number"
    assert "|" in findings[0].message


def test_preflight_finds_a_row_whose_cell_count_disagrees():
    findings = preflight("| a | b |\n|---|---|\n| one | two | three |\n")

    assert [f.line for f in findings] == [3]


def test_preflight_finds_unterminated_math():
    assert [f.line for f in preflight("A paragraph with $x + y and no closer.\n")] == [1]


def test_preflight_finds_an_unbalanced_fence():
    assert [f.line for f in preflight("Intro.\n\n```python\nx = 1\n")] == [3]


def test_preflight_is_quiet_on_clean_input():
    """
    High precision is the whole point. A check that fires on ordinary documents
    would relabel every real flowmark bug as "your input is ambiguous", which is
    worse than the message it replaces.
    """
    clean = (
        "# Title\n\nA paragraph with $x + y$ inline math and `code | with a bar`.\n\n"
        "| a | b |\n|---|---|\n| one | two |\n\n```python\nx = 1\n```\n\n"
        "A price of $5 and another of $10.\n"
    )

    assert preflight(clean) == []


@pandocless
def test_verify_failure_on_ambiguous_input_does_not_blame_flowmark():
    """
    The #17 part 3 ask: when verification fails *and* preflight finds a suspect
    construct, say the input is ambiguous and name it, rather than asserting a
    defect no report can fix.
    """
    with pytest.raises(MeaningChangedError) as excinfo:
        reformat_text(AMBIGUOUS_TABLE, semantic=True, verify=True, verify_label="doc.md")

    message = str(excinfo.value)
    assert "flowmark bug" not in message, message
    assert "doc.md:3" in message, message
    assert "ambiguous" in message.lower(), message


def test_verify_failure_on_clean_input_keeps_the_original_message(
    monkeypatch: pytest.MonkeyPatch,
):
    """
    When preflight finds nothing to blame, a genuine verify failure keeps its
    original "flowmark bug" wording rather than being relabelled as the user's
    fault.

    The gate is forced to fire rather than pinned to a live defect. This test used
    #30's document -- smartquotes half-converting a single-quoted span nested in a
    double-quoted one -- but fixing #30 made that input verify clean, so a pinned
    test started failing the day the bug it named was fixed. Forcing the failure
    keeps the check on the attribution branch (preflight-clean input must not be
    relabelled), which is what is under test here, not the detection.
    """

    def refuse(source: str, result: str, label: str = "input") -> list[str]:
        detail = "block 0: Para content differs"
        raise MeaningChangedError(
            f"Refusing to write {label}: reformatting would change what pandoc reads "
            f"({detail}). The file is unchanged. "
            f"This is a flowmark bug -- please report it with the input document. To skip "
            f"this check and format anyway, pass --no-verify.",
            detail=detail,
        )

    monkeypatch.setattr("flowmark.reformat_api.check_meaning_preserved", refuse)

    # Clean input that reformatting genuinely changes (collapsed spaces) but in which
    # preflight finds no suspect construct, so the attribution branch must not relabel.
    clean_but_reformatted = "# Title\n\nsome   text   here\n"
    assert preflight(clean_but_reformatted) == []

    with pytest.raises(MeaningChangedError) as excinfo:
        reformat_text(clean_but_reformatted, verify=True, verify_label="doc.md")

    message = str(excinfo.value)
    assert "flowmark bug" in message, message
    assert "ambiguous" not in message.lower(), message
