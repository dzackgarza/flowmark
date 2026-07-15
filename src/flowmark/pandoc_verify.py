"""
Verify that reformatting did not change what pandoc reads.

Flowmark is free to change a construct's *spelling* -- rewrapping prose, fencing
an indented code block, curling a quote -- but never its *meaning*.  Pandoc owns
the definition of meaning for the documents this fork targets, so it is the
authority to ask, rather than re-deriving its grammar here and hoping.

Most of flowmark's deliberate spelling changes are already invisible to pandoc's
reader, so they need no special handling here: indented and fenced code blocks
both read as `CodeBlock`, footnote definitions read the same with or without a
blank line between them, and pandoc's `smart` extension (on by default for
`markdown`) folds straight and curly quotes alike into `Quoted`, which covers
`smartquotes`.

Two do need canonicalizing before comparison, both concerning inline whitespace:

- Rewrapping a paragraph turns a `Space` into a `SoftBreak` and back.  This is
  flowmark's whole purpose, so comparing them strictly would reject every run.
- `ellipses` rewrites `then...` to `then …`, inserting a space by design (its
  "normalized spacing").

So inline text is compared as a whitespace-normalized stream rather than
token-for-token.  Whitespace *between* inlines is spelling; everything else --
every element type, every nesting relationship, and the text itself -- is
compared exactly, which is what catches a `Str` becoming an `Emph` or a `Div`
shedding its contents.

This needs the `pandoc` binary on PATH.  It is not a fallback that quietly
degrades when pandoc is missing: callers asking to verify get an error.
"""

import json
import re
import shutil
import subprocess
from typing import Any

PANDOC_FORMAT = "markdown"
"""Pandoc's own markdown dialect -- the one these documents are written in.

Deliberately not `commonmark_x`, which is the only dialect that can emit source
positions but which parses fenced divs differently: it terminates a div at a
`:::` inside a fenced code block, where `markdown` does not.
"""


class PandocUnavailableError(RuntimeError):
    """Raised when verification is requested but the pandoc binary is not on PATH."""


class MeaningChangedError(ValueError):
    """Raised when reformatting changed the document's parsed AST."""


def pandoc_ast(markdown_text: str) -> list[Any]:
    """
    Return pandoc's parsed block list for `markdown_text`.

    Raises:
        PandocUnavailableError: if the pandoc binary is not on PATH.
        MeaningChangedError: never; see `check_meaning_preserved`.
    """
    pandoc_exe = shutil.which("pandoc")
    if pandoc_exe is None:
        raise PandocUnavailableError(
            "Verification requires the `pandoc` binary on PATH. "
            "Install pandoc (https://pandoc.org/installing.html) or drop --verify."
        )

    proc = subprocess.run(
        [pandoc_exe, "-f", PANDOC_FORMAT, "-t", "json"],
        input=markdown_text,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise PandocUnavailableError(f"pandoc failed to parse the document: {proc.stderr.strip()}")

    return json.loads(proc.stdout)["blocks"]


def _block_types(blocks: list[Any]) -> list[str]:
    return [b.get("t", "?") for b in blocks]


_SPACE_INLINES = frozenset({"Space", "SoftBreak"})


def _normalize_text(text: str) -> str:
    """Collapse whitespace runs, and drop the space `ellipses` inserts before `…`."""
    return re.sub(r"\s+(?=…)", "", re.sub(r"\s+", " ", text))


def _canonical(node: Any) -> Any:
    """
    Rewrite `node` so that inline whitespace differences compare equal.

    Runs of `Str`/`Space`/`SoftBreak` collapse into a single normalized `Str`.
    Anything else is structure and is preserved exactly, so this cannot hide a
    changed element type, a changed nesting, or changed words.
    """
    if isinstance(node, dict):
        return {k: _canonical(v) for k, v in node.items()}  # pyright: ignore[reportUnknownVariableType]
    if not isinstance(node, list):
        return node

    out: list[Any] = []
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        text = _normalize_text("".join(buffer))
        buffer.clear()
        if text:
            out.append({"t": "Str", "c": text})

    for item in node:  # pyright: ignore[reportUnknownVariableType]
        if isinstance(item, dict):
            kind = item.get("t")  # pyright: ignore[reportUnknownMemberType]
            if kind in _SPACE_INLINES:
                buffer.append(" ")
                continue
            if kind == "Str":
                buffer.append(str(item.get("c", "")))  # pyright: ignore[reportUnknownMemberType]
                continue
        flush()
        out.append(_canonical(item))
    flush()
    return out


def check_meaning_preserved(source: str, result: str, label: str = "input") -> None:
    """
    Raise `MeaningChangedError` if `result` does not parse to the same pandoc AST
    as `source`.

    Args:
        source: the original markdown.
        result: the reformatted markdown.
        label: how to name the document in the error message.
    """
    source_ast = pandoc_ast(source)
    result_ast = pandoc_ast(result)
    if _canonical(source_ast) == _canonical(result_ast):
        return

    before, after = _block_types(source_ast), _block_types(result_ast)
    detail = (
        f"blocks {before} -> {after}" if before != after else "same block types, altered content"
    )
    raise MeaningChangedError(
        f"Reformatting changed what pandoc reads from {label} ({detail}). "
        f"This is a flowmark bug: the output was not written. "
        f"Please report it with the input document."
    )
