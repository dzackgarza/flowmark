"""
A verify refusal on one file must not abort a multi-file batch.

The pandoc render-guard's job is to protect the individual document: leave it
byte-identical and report the refusal. Failing the entire batch on the first
unsafe file blocks formatting of every other file (and freezes any QC gate
that formats a whole corpus per commit) even though those files are fine.

Single-document calls (`reformat_text`, one explicit file) still raise, so a
caller formatting one document sees a visible failure.
"""

from pathlib import Path
from textwrap import dedent

import pytest

from flowmark.pandoc_verify import MeaningChangedError
from flowmark.reformat_api import reformat_file, reformat_files

# Ambiguous markdown: an unescaped `|` from a linear system inside inline math,
# in a pipe-table row (the #17 reporter's actual line). Pandoc already mis-parses
# the row -- the three logical cells read as five -- so reflowing the table
# shuffles the mis-split differently and verify correctly refuses.
#
# This fixture was previously a paragraph followed by a tight list. That was a
# live bug (#16), and pinning a test to a live bug means the test fails the day it
# is fixed -- which is exactly what happened when the `lazy_list` normalization
# landed. The refusal here is not a flowmark defect due to be fixed: the input is
# genuinely ambiguous, so this document keeps refusing by design.
AMBIGUOUS = dedent(
    """\
    | col | status | ref |
    |---|---|---|
    | $|-2K_{\\widetilde V}|=\\{C\\}$ generically | established | @sec:anti-bicanonical |
    """
)

NEEDS_FORMAT = "A paragraph with an accidentally   wide gap.  Another sentence here.\n"


def test_batch_skips_refused_file_and_formats_the_rest(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.md"
    good = tmp_path / "good.md"
    bad.write_text(AMBIGUOUS)
    good.write_text(NEEDS_FORMAT)

    # Must not raise: the refusal is per-file, not batch-fatal.
    reformat_files([str(bad), str(good)], inplace=True, nobackup=True, semantic=True)

    assert bad.read_text() == AMBIGUOUS, "refused file must be byte-identical"
    assert good.read_text() != NEEDS_FORMAT, "other files must still be formatted"

    err = capsys.readouterr().err
    assert "bad.md" in err and "Refusing to write" in err, "refusal must be reported"
    assert "1 file left unformatted" in err, "batch must summarize skips"


def test_single_file_call_still_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.md"
    bad.write_text(AMBIGUOUS)
    with pytest.raises(MeaningChangedError):
        reformat_file(str(bad), output=None, inplace=True, nobackup=True, semantic=True)
    assert bad.read_text() == AMBIGUOUS
