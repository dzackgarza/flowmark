"""
Tests for the pandoc AST oracle.

The oracle exists so flowmark stops re-deriving pandoc's grammar by hand and
hoping: pandoc owns what these documents mean, so it is the thing to ask. The
contract it enforces is "flowmark may change spelling; it may never change what
pandoc reads."

These are skipped without the pandoc binary, so contributors without it are not
blocked. CI has pandoc and runs them.
"""

import shutil

import pytest

from flowmark.pandoc_verify import (
    MeaningChangedError,
    PandocUnavailableError,
    check_meaning_preserved,
)
from flowmark.reformat_api import reformat_text
from flowmark.typography.ellipses import ellipses

pandocless = pytest.mark.skipif(
    shutil.which("pandoc") is None, reason="requires the pandoc binary on PATH"
)


# Each pair is a reproducer and the bytes flowmark actually emitted for it before
# the fix -- captured by running the pre-fix code, not hand-written, so these are
# the real defects rather than a guess at their shape. An oracle that misses any
# of them would not have been worth adding.
PRE_FIX_CORRUPTIONS = [
    pytest.param(
        "::: proof\nBody.\n:::\n",
        ":::\nproof\nBody.\n:::\n",
        id="3-bare-class-div-lost",
    ),
    pytest.param(
        "Text.[^1] More text.[^2]\n\n[^1]: First note.\n[^2]: Second note.\n",
        "Text.[^1] More text.[^2]\n\n[^1]: First note. [^2]: Second note.\n\n",
        id="5-footnote-deleted",
    ),
    pytest.param(
        "::: {.a}\nO.\n\n::: {.b}\nI.\n:::\n\nA.\n:::\n",
        ":::{.a}\nO.\n\n::: {.b}\nI.\n:::\n\nA.\n:::\n:::\n",
        id="6-div-content-escapes",
    ),
    pytest.param(
        "    literal code\n\nAfter.\n",
        "literal code\n\nAfter.\n",
        id="7-code-becomes-prose",
    ),
    pytest.param(
        "A \\overline{ \\mathcal{M}_{1} } b y_{2} c.\n",
        "A \\overline{ \\mathcal{M}*{1} } b y*{2} c.\n",
        id="8-raw-tex-becomes-emphasis",
    ),
    pytest.param(
        "::: {.foo}\n```\n:::\n```\nAfter.\n:::\n",
        "::: {.foo}\n```\n:::\n```\nAfter.\n:::\n```\n",
        id="6-colon-run-in-code-block",
    ),
]


@pandocless
@pytest.mark.parametrize(("source", "corrupted"), PRE_FIX_CORRUPTIONS)
def test_oracle_catches_every_real_meaning_change(source: str, corrupted: str):
    """
    The oracle must fail on output that changed meaning -- otherwise it proves
    nothing. Two of these (#5, #8) differ from their source only *within* a
    block, which is what pins the inline whitespace normalization: it must not
    be loose enough to let a deleted footnote or a mangled TeX command through.
    """
    with pytest.raises(MeaningChangedError):
        check_meaning_preserved(source, corrupted)


@pandocless
def test_oracle_accepts_a_deliberate_spelling_change():
    """
    Flowmark rewrites an indented code block to a fenced one. Different bytes,
    same `CodeBlock` -- the oracle must not object.
    """
    check_meaning_preserved("    literal code\n", "```\nliteral code\n```\n")


@pandocless
def test_oracle_accepts_rewrapped_prose():
    """Rewrapping is flowmark's whole job; pandoc reads the same Para either way."""
    source = "One sentence here. Another sentence there.\n"
    rewrapped = "One sentence here.\nAnother sentence there.\n"

    check_meaning_preserved(source, rewrapped)


@pandocless
@pytest.mark.parametrize(
    "source",
    [
        # #3: fenced div attribute specs.
        '::: {#thm .theorem title="{[@AEGS23, Thm. 1.1]}"}\nBody.\n:::\n',
        "::: proof\nBody.\n:::\n",
        ":::::::: proof\nBody.\n::::::::\n",
        # #5: footnote definitions.
        "Text.[^1] More.[^2]\n\n[^1]: First.\n[^2]: Second.\n",
        "T.[^1]\n\n[^1]:\n    First para.\n\n    Second para.\n",
        # #6: nested divs, including colon runs inside code blocks.
        "::: {.theorem}\nOuter.\n\n::: {.proof}\nInner.\n:::\n\nAfter.\n:::\n",
        "::: {.foo}\n```\n:::\n```\nAfter.\n:::\n",
        "::: {.foo}\n```\n::: {.bar}\n```\nAfter.\n:::\n",
        "::: {.foo}\n~~~\n:::\n~~~\nAfter.\n:::\n",
        # #7: indented code blocks.
        "    literal code\n\nAfter.\n",
        # #8: raw inline TeX.
        "A \\overline{ \\mathcal{M}_{1} } b y_{2} c.\n",
        "A $\\overline{ \\mathcal{M}_{1} }$ b $y_{2}$ c.\n",
    ],
)
def test_reformatting_preserves_meaning(source: str):
    """
    Every construct family in PR #4, checked against pandoc rather than against
    an expected string a human guessed at.
    """
    reformat_text(source, verify=True)


@pandocless
def test_smartquotes_passes_verification():
    """
    `smartquotes` is invisible to pandoc for free -- its `smart` extension folds
    straight and curly quotes alike into `Quoted`.
    """
    reformat_text('He said "hi" and there.\n', verify=True, smartquotes=True)


@pandocless
@pytest.mark.parametrize(
    "source",
    [
        "He said... yes\n",  # space already after: the easy case
        "word...word\n",  # ellipses inserts a space on BOTH sides
        "a...b and c... d\n",
        "Wait...\n",
    ],
)
def test_ellipsis_spacing_is_not_a_meaning_change(source: str):
    """
    `ellipses` respells text (`word...word` -> `word … word`) without changing
    what it means, so the oracle must stay quiet for it.

    The expected output comes from `ellipses()` itself rather than a literal, so
    this is pinned to the contract's owner: if `typography/ellipses.py` changes
    its spacing rule, this test picks the new rule up and fails here if the
    oracle cannot tolerate it -- instead of the two drifting apart in silence.
    """
    check_meaning_preserved(source, ellipses(source))
    reformat_text(source, verify=True, ellipses=True)


def test_verify_is_off_by_default(monkeypatch: pytest.MonkeyPatch):
    """
    Verification costs two pandoc subprocesses per document, so it must be opt-in.

    Hiding pandoc is what makes this a real test: with `verify` defaulting on,
    `reformat_text` would raise `PandocUnavailableError` here. Asserting the
    output alone would pass either way and prove nothing.
    """
    monkeypatch.setattr("flowmark.pandoc_verify.shutil.which", lambda _: None)

    assert reformat_text("Hi.\n") == "Hi.\n"


def test_missing_pandoc_fails_loudly(monkeypatch: pytest.MonkeyPatch):
    """
    A missing binary must raise, not silently skip the check. A verification that
    quietly passes when it cannot run is worse than none.
    """
    monkeypatch.setattr("flowmark.pandoc_verify.shutil.which", lambda _: None)

    with pytest.raises(PandocUnavailableError, match="pandoc"):
        reformat_text("Hi.\n", verify=True)
