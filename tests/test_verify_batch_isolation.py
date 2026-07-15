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

# Ambiguous markdown: CommonMark (flowmark's parser) reads a list interrupting
# the paragraph, pandoc reads one paragraph. Loose-list normalization would
# insert a blank line and change what pandoc reads, so verify must refuse.
AMBIGUOUS = dedent(
    """\
    Extracts the side:
    - item one
    - item two
    """
)

NEEDS_FORMAT = "A paragraph with an accidentally   wide gap.  Another sentence here.\n"


def test_batch_skips_refused_file_and_formats_the_rest(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
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


def test_single_file_call_still_raises(tmp_path: Path):
    bad = tmp_path / "bad.md"
    bad.write_text(AMBIGUOUS)
    with pytest.raises(MeaningChangedError):
        reformat_file(str(bad), output=None, inplace=True, nobackup=True, semantic=True)
    assert bad.read_text() == AMBIGUOUS
