"""
Verify that reformatting did not *unintentionally* change what pandoc reads.

Flowmark normalizes documents to an opinionated style, so full AST preservation
is not the contract and cannot be: some normalizations deliberately change the
parsed AST.  A bold heading is stripped because the `<h1>`/`\\section` element
should carry that weight rather than hand-applied bolding, and list spacing is
standardized rather than letting each document control presentation.  Deliberate
style changes like these are the formatter doing its job, so they never gate a
run; they are at most *reported* (a stderr note when one applies without having
been asked for); see `_NORMALIZATIONS`.

Every *other* AST change is data being destroyed by accident -- a construct the
formatter mishandles rather than an opinion it holds -- and that is what this
check exists to catch.  Pandoc owns the definition of what these documents say,
so it is the authority to ask, rather than re-deriving its grammar here and
hoping.

Some of flowmark's deliberate spelling changes are already invisible to pandoc's
reader, so they need no special handling here: indented and fenced code blocks
both read as `CodeBlock`, and footnote definitions read the same with or without a
blank line between them.

`smartquotes` is *not* one of them, contrary to what this module assumed until
issue #27.  Pandoc's `smart` extension does not fold straight and curly quotes
into the same reading: `"hi"` is `Quoted DoubleQuote [Str "hi"]` and `“hi”` is a
literal `Str` (checked against pandoc 3.9.0.2).  Curling a quote is therefore a
real AST change and needs a declared normalization like any other opinion; see
`SMART_QUOTES`.

Two do need canonicalizing before comparison, both concerning inline whitespace:

- Rewrapping a paragraph turns a `Space` into a `SoftBreak` and back.  This is
  flowmark's whole purpose, so comparing them strictly would reject every run.
- `ellipses` inserts a space on *either side* of the ellipsis it creates
  (`word...word` -> `word … word`), per the rule documented on
  `flowmark.typography.ellipses.ellipses`, which owns that contract.

So inline text is compared as a whitespace-normalized stream rather than
token-for-token, and whitespace adjacent to an ellipsis is dropped on both
sides.  Whitespace *between* inlines is spelling; everything else -- every
element type, every nesting relationship, and the text itself -- is compared
exactly, which is what catches a `Str` becoming an `Emph` or a `Div` shedding
its contents.

The ellipsis rule is owned by `typography/ellipses.py`, not here.  This module
only declares spacing around an ellipsis to be out of scope; if that contract
changes, `test_pandoc_verify.py` drives its cases from `ellipses()` itself, so
the divergence surfaces as a failing test rather than silently.

This needs the `pandoc` binary on PATH.  It is not a fallback that quietly
degrades when pandoc is missing: callers asking to verify get an error.
"""

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from itertools import combinations
from typing import Any

PANDOC_FORMAT = "markdown"
"""Pandoc's own markdown dialect -- the one these documents are written in.

Deliberately not `commonmark_x`, which is the only dialect that can emit source
positions but which parses fenced divs differently: it terminates a div at a
`:::` inside a fenced code block, where `markdown` does not.
"""


class PandocUnavailableError(RuntimeError):
    """Raised when verification is requested but the pandoc binary is not on PATH."""


class PandocParseError(ValueError):
    """
    Raised when pandoc is present but rejects the document.

    Distinct from `PandocUnavailableError`: pandoc ran and did its job.  Conflating
    the two would report a malformed document as a missing install.
    """


class MeaningChangedError(ValueError):
    """Raised when reformatting changed the document's parsed AST."""


def _pandoc_exe() -> str:
    pandoc_exe = shutil.which("pandoc")
    if pandoc_exe is None:
        raise PandocUnavailableError(
            "Verification requires the `pandoc` binary on PATH. "
            "Install pandoc (https://pandoc.org/installing.html) or drop --verify."
        )
    return pandoc_exe


def _spawn_pandoc(pandoc_exe: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [pandoc_exe, "-f", PANDOC_FORMAT, "-t", "json"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _collect_blocks(proc: subprocess.Popen[str], markdown_text: str) -> list[Any]:
    stdout, stderr = proc.communicate(markdown_text)
    if proc.returncode != 0:
        raise PandocParseError(f"pandoc could not parse the document: {stderr.strip()}")
    blocks: list[Any] = json.loads(stdout)["blocks"]
    return blocks


def pandoc_ast(markdown_text: str) -> list[Any]:
    """
    Return pandoc's parsed block list for `markdown_text`.

    Raises:
        PandocUnavailableError: if the pandoc binary is not on PATH.
        PandocParseError: if pandoc ran but could not parse the document.
    """
    return _collect_blocks(_spawn_pandoc(_pandoc_exe()), markdown_text)


def _pandoc_ast_pair(source: str, result: str) -> tuple[list[Any], list[Any]]:
    """
    Parse both documents with two concurrent pandoc processes.

    A comparison always needs both trees, and pandoc's startup dominates the
    cost, so overlapping the two runs roughly halves verification latency.
    """
    pandoc_exe = _pandoc_exe()
    source_proc = _spawn_pandoc(pandoc_exe)
    result_proc = _spawn_pandoc(pandoc_exe)
    try:
        source_blocks = _collect_blocks(source_proc, source)
    except Exception:
        result_proc.kill()
        result_proc.communicate()
        raise
    return source_blocks, _collect_blocks(result_proc, result)


def _block_types(blocks: list[Any]) -> list[str]:
    return [block.get("t", "?") for block in blocks]


_SPACE_INLINES = frozenset({"Space", "SoftBreak"})


def _normalize_text(text: str) -> str:
    """
    Collapse whitespace runs, and drop whitespace on either side of an ellipsis.

    `ellipses` inserts a space on *both* sides (`word...word` -> `word … word`),
    so stripping only the leading one makes this fire on valid output.  That rule
    is owned by `flowmark.typography.ellipses`; this only declares spacing around
    an ellipsis out of scope for the comparison.
    """
    return re.sub(r"\s*…\s*", "…", re.sub(r"\s+", " ", text))


def _canonical(node: Any) -> Any:
    """
    Rewrite `node` so that inline whitespace differences compare equal.

    Runs of `Str`/`Space`/`SoftBreak` collapse into a single normalized `Str`.
    Anything else is structure and is preserved exactly, so this cannot hide a
    changed element type, a changed nesting, or changed words.
    """
    if isinstance(node, dict):
        mapping: dict[str, Any] = node
        return {key: _canonical(value) for key, value in mapping.items()}
    if not isinstance(node, list):
        return node

    items: list[Any] = node
    out: list[Any] = []
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        text = _normalize_text("".join(buffer))
        buffer.clear()
        if text:
            out.append({"t": "Str", "c": text})

    for item in items:
        if isinstance(item, dict):
            element: dict[str, Any] = item
            kind = element.get("t")
            if kind in _SPACE_INLINES:
                buffer.append(" ")
                continue
            if kind == "Str":
                buffer.append(str(element.get("c", "")))
                continue
        flush()
        out.append(_canonical(item))
    flush()
    return out


def _unbold_headings(node: Any) -> Any:
    """
    Unwrap a heading whose entire content is bold, on both sides of a comparison.

    Flowmark's `cleanups` deliberately strips this: a heading's weight is the
    `<h1>`/`\\section` element's job, and bolding it by hand adds nothing but
    non-uniformity.  So `Header[Strong[x]]` -> `Header[x]` is a normalization,
    not a loss -- but it *is* an AST change, so it is reported as one.
    """
    if isinstance(node, dict):
        mapping: dict[str, Any] = node
        out = {key: _unbold_headings(value) for key, value in mapping.items()}
        if out.get("t") == "Header":
            content: Any = out.get("c")
            if isinstance(content, list) and len(content) == 3:  # pyright: ignore[reportUnknownArgumentType]
                parts: list[Any] = content
                inlines = parts[2]
                if isinstance(inlines, list) and len(inlines) == 1:  # pyright: ignore[reportUnknownArgumentType]
                    only: Any = inlines[0]
                    if isinstance(only, dict) and only.get("t") == "Strong":  # pyright: ignore[reportUnknownMemberType]
                        out["c"] = [parts[0], parts[1], only.get("c")]  # pyright: ignore[reportUnknownMemberType]
        return out
    if isinstance(node, list):
        items: list[Any] = node
        return [_unbold_headings(item) for item in items]
    return node


def _plain_to_para(node: Any) -> Any:
    """
    Treat `Plain` and `Para` as one, on both sides of a comparison.

    This is the only thing that distinguishes a tight list from a loose one, and
    standardizing list spacing is what `list_spacing` is for.  Same story as
    headings: a deliberate normalization that shows up as an AST change.
    """
    if isinstance(node, dict):
        mapping: dict[str, Any] = node
        out = {key: _plain_to_para(value) for key, value in mapping.items()}
        if out.get("t") == "Plain":
            out["t"] = "Para"
        return out
    if isinstance(node, list):
        items: list[Any] = node
        return [_plain_to_para(item) for item in items]
    return node


_QUOTE_MARKS = {"DoubleQuote": ("“", "”"), "SingleQuote": ("‘", "’")}


def _flatten_quoted(node: Any) -> Any:
    """
    Replace a `Quoted` span with its curled spelling, on both sides of a comparison.

    Pandoc's `smart` extension does *not* fold straight and curly quotes into the
    same reading, contrary to what this module long assumed: a straight `"hi"` is
    `Quoted DoubleQuote [Str "hi"]`, while the curled `“hi”` is a literal
    `Str`.  So curling a quote -- which is all `smartquotes` does -- genuinely
    changes the AST, and without this entry the released `--smartquotes` flag is
    refused by the gate on any document containing a straight quote.

    Writing the marks *into* the stream, rather than dropping the `Quoted` wrapper,
    is what keeps this narrow: a quote that was deleted or whose pairing moved
    lands its marks somewhere else in the text and still mismatches.
    """
    if isinstance(node, dict):
        mapping: dict[str, Any] = node
        return {key: _flatten_quoted(value) for key, value in mapping.items()}
    if not isinstance(node, list):
        return node

    items: list[Any] = node
    out: list[Any] = []
    for item in items:
        quoted = _as_quoted(item)
        if quoted is None:
            out.append(_flatten_quoted(item))
            continue
        (open_mark, close_mark), inner = quoted
        out.append({"t": "Str", "c": open_mark})
        out.extend(_flatten_quoted(inner))
        out.append({"t": "Str", "c": close_mark})
    return out


def _as_quoted(item: Any) -> tuple[tuple[str, str], Any] | None:
    """Return `((open, close), inlines)` if `item` is a `Quoted` span, else None."""
    if not isinstance(item, dict) or item.get("t") != "Quoted":  # pyright: ignore[reportUnknownMemberType]
        return None
    content: Any = item.get("c")  # pyright: ignore[reportUnknownMemberType]
    if not isinstance(content, list) or len(content) != 2:  # pyright: ignore[reportUnknownArgumentType]
        return None
    parts: list[Any] = content
    kind: Any = parts[0]
    if not isinstance(kind, dict):
        return None
    marks = _QUOTE_MARKS.get(str(kind.get("t")))  # pyright: ignore[reportUnknownMemberType]
    return None if marks is None else (marks, parts[1])


UNBOLD_HEADING = "unbold_heading"
"""Identifier for the heading-unbolding normalization; requested by `cleanups`."""

LIST_SPACING = "list_spacing"
"""Identifier for the tight/loose list normalization; requested by `list_spacing`."""

SMART_QUOTES = "smart_quotes"
"""Identifier for the quote-curling normalization; requested by `smartquotes`."""

Normalization = Callable[[Any, Any], tuple[Any, Any]]
"""A declared normalization: rewrites the two canonicalized trees so the change it
declares compares equal, and returns them.

Taking *both* trees rather than one node is what lets an entry be **directional**.
Most opinions are symmetric -- unbolding a heading means the same thing whichever
side it is seen on -- and `_both` lifts a plain node transform into this shape.
But an entry may need to accept a change in one direction while still refusing its
reverse, and a single-node transform cannot express that: rewriting both sides the
same way necessarily accepts the corruption that undoes the opinion.
"""


def _both(node_transform: Callable[[Any], Any]) -> Normalization:
    """Lift a symmetric node transform into a `Normalization` over both trees."""

    def normalize(before: Any, after: Any) -> tuple[Any, Any]:
        return node_transform(before), node_transform(after)

    return normalize


def _normalize_quotes(before: Any, after: Any) -> tuple[Any, Any]:
    """
    Flatten `Quoted` spans on both sides, then re-canonicalize.

    The re-canonicalization is not optional: `_flatten_quoted` emits each quote
    mark as its own `Str`, and the side that was *already* curled carries the mark
    inside a neighbouring `Str` (`Str "“a"`).  Only after the `Str` run is merged
    again do the two spell the same thing.
    """
    return _canonical(_flatten_quoted(before)), _canonical(_flatten_quoted(after))


_NORMALIZATIONS: list[tuple[str, str, Normalization]] = [
    (UNBOLD_HEADING, "removed bold from a heading", _both(_unbold_headings)),
    (LIST_SPACING, "changed list spacing (tight/loose)", _both(_plain_to_para)),
    (SMART_QUOTES, "curled straight quotes", _normalize_quotes),
]
"""Flowmark's intentional, opinionated style normalizations.

These genuinely change the parsed AST, so full AST preservation is not the
contract.  They are not meaning being lost -- they are the formatter doing its
job -- so they are allowed.  Every *other* AST change is a bug and raises.

Callers are told which ones applied so they can report the ones the caller did
not ask for: unbolding a heading is unremarkable under `cleanups` and worth
saying out loud without it.

## What an entry may claim

An entry declares *one* opinion the formatter holds about spelling, named by its
identifier and described in the second field for the user-facing report.  It may
not stand in for a family of changes, and it may not be widened to make an
unrelated failure pass: the question an entry answers is "did flowmark do the
specific thing this opinion describes?", never "is this difference tolerable?".

## How narrowly it must be scoped

An entry is admissible only if the gate is no weaker for its presence.  Concretely,
the rewrite must not make a *corruption* of the same shape compare equal.  That is
the whole reason `Normalization` sees both trees: an opinion that *materializes*
structure must rewrite only the side that gained it, and only when the rewrite
reproduces the other side exactly, so the reverse -- structure the formatter
destroyed -- still mismatches and still raises.  A symmetric rewrite of both sides
cannot make that distinction, and `_both` is therefore only for opinions where the
reverse is not a corruption worth catching.

## What proof it owes

Every entry carries, in `tests/test_pandoc_verify.py`'s `NORMALIZATION_CONTRACT`
table, both:

- a **positive case**: a source/result pair this entry must accept, attributed to
  this entry and no other; and
- a **negative case**: a *nearby* source/result pair -- the same construct, the
  same shape -- that must still raise `MeaningChangedError`.

`test_every_normalization_declares_its_contract` asserts the table covers
`_NORMALIZATIONS` exactly, so an entry cannot be added without both cases.
"""


def describe(normalization: str) -> str:
    """Human-readable text for a normalization identifier."""
    return next(text for key, text, _ in _NORMALIZATIONS if key == normalization)


def check_meaning_preserved(source: str, result: str, label: str = "input") -> list[str]:
    """
    Check that `result` means what `source` did, allowing flowmark's intentional
    style normalizations.

    Returns the normalizations that were needed to reconcile the two, so the
    caller can report them; an empty list means the ASTs matched outright.

    Raises:
        MeaningChangedError: if the two differ by anything else.
    """
    source_ast, result_ast = _pandoc_ast_pair(source, result)
    before_canon, after_canon = _canonical(source_ast), _canonical(result_ast)
    if before_canon == after_canon:
        return []

    # Attribute the difference to the smallest set of normalizations that
    # reconciles it.  Merely containing a construct a normalization rewrites
    # (a bold heading or tight list that formatting *preserved*) must not
    # count as that normalization having been applied.
    for size in range(1, len(_NORMALIZATIONS) + 1):
        for combo in combinations(_NORMALIZATIONS, size):
            normalized_before, normalized_after = before_canon, after_canon
            for _key, _text, normalize in combo:
                normalized_before, normalized_after = normalize(normalized_before, normalized_after)
            if normalized_before == normalized_after:
                return [key for key, _text, _normalize in combo]

    before, after = _block_types(source_ast), _block_types(result_ast)
    detail = (
        f"blocks {before} -> {after}" if before != after else "same block types, altered content"
    )
    raise MeaningChangedError(
        f"Refusing to write {label}: reformatting would change what pandoc reads "
        f"({detail}). The file is unchanged. This is a flowmark bug -- please report it "
        f"with the input document. To skip this check and format anyway, pass --no-verify."
    )
