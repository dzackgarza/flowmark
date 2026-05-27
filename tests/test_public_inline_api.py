"""Tests for the public Markdown-inline API: flowmark.atomic and flowmark.ast."""

from __future__ import annotations

from flowmark import (
    ATOMIC_CONSTRUCT_PATTERN,
    ATOMIC_PATTERNS,
    MARKDOWN_INLINE_PATTERNS,
    AtomicPattern,
    Link,
    extract_links,
    flowmark_markdown,
    iter_inline,
)
from flowmark.atomic import INLINE_CODE_SPAN, MARKDOWN_LINK


def _parse(text: str):
    return flowmark_markdown().parse(text)


def test_atomic_exports_present():
    assert isinstance(ATOMIC_PATTERNS, tuple)
    assert all(isinstance(p, AtomicPattern) for p in ATOMIC_PATTERNS)
    assert MARKDOWN_INLINE_PATTERNS == (INLINE_CODE_SPAN, MARKDOWN_LINK)
    # Both prose patterns are members of the full wrapping set.
    assert set(MARKDOWN_INLINE_PATTERNS).issubset(set(ATOMIC_PATTERNS))


def test_atomic_construct_pattern_matches_link_and_code():
    text = "see [a](http://x.com) and `code`"
    matches = [m.group(0) for m in ATOMIC_CONSTRUCT_PATTERN.finditer(text)]
    assert "[a](http://x.com)" in matches
    assert "`code`" in matches


def test_extract_inline_link_with_title():
    doc = _parse('See [text](http://x.com "the title") here.\n')
    assert extract_links(doc) == [Link("text", "http://x.com", "the title")]


def test_extract_reference_link_resolves_destination():
    doc = _parse("See [text][r].\n\n[r]: http://ref.com\n")
    assert extract_links(doc) == [Link("text", "http://ref.com", None)]


def test_images_excluded_by_default_included_on_request():
    doc = _parse("![alt](img.png)\n")
    assert extract_links(doc) == []
    assert extract_links(doc, include_images=True) == [Link("alt", "img.png", None)]


def test_autolinks_controlled_by_flag():
    doc = _parse("<http://auto.com>\n")
    assert extract_links(doc) == [Link("http://auto.com", "http://auto.com", None)]
    assert extract_links(doc, include_autolinks=False) == []


def test_extract_links_document_order():
    doc = _parse("[one](http://1.com) then [two](http://2.com)\n")
    assert [link.url for link in extract_links(doc)] == ["http://1.com", "http://2.com"]


def test_iter_inline_is_read_only_and_finds_link():
    doc = _parse("a [b](http://x.com) c\n")
    from marko import inline

    before = flowmark_markdown().render(doc)
    links = [el for el in iter_inline(doc) if isinstance(el, inline.Link)]
    assert len(links) == 1
    # Tree unchanged after iteration.
    assert flowmark_markdown().render(doc) == before
