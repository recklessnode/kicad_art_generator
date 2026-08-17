#!/usr/bin/env python3
"""Expand an SVG's internal DTD entities so a hardened XML parser will read it.

Why this exists
---------------
Adobe Illustrator writes an internal DTD subset declaring its private
namespaces as entities, then references them in the root element::

    <!DOCTYPE svg PUBLIC "..." "..." [
        <!ENTITY ns_extend "http://ns.adobe.com/Extensibility/1.0/">
        ...
    ]>
    <svg xmlns:x="&ns_extend;" ...>

cairosvg parses through defusedxml, which rejects ANY entity declaration
outright (`EntitiesForbidden`) because entity expansion is the billion-laughs /
XXE attack surface. The result is that two perfectly ordinary Illustrator
exports -- the MFB node badges -- could not be rasterised at all.

defusedxml is right to refuse; the fix is not to weaken it. Instead this module
resolves the entities itself, with the two properties defusedxml is protecting
against explicitly bounded:

  * expansion is capped (depth and total size), so a billion-laughs document
    fails loudly instead of exhausting memory;
  * only INTERNAL entities are honoured. An external entity (SYSTEM/PUBLIC) is
    never fetched -- that is the XXE vector -- it is a hard error.

Nothing is dropped quietly. An entity reference that is not declared and not an
XML built-in raises, rather than being stripped and leaving the document subtly
different from the artwork the designer drew.

Dependency-free on purpose: both tools/prep_assets.py (ingest) and
tools/emit_art.py (emission) rasterise SVGs, and there must be one
implementation of this, not two.
"""
from __future__ import annotations

import re

__all__ = ["expand_internal_entities", "read_svg_bytes", "SvgEntityError"]

# The five entities XML defines itself; a document may reference these without
# declaring them, and they must survive untouched.
XML_BUILTINS = {"amp", "lt", "gt", "quot", "apos"}

MAX_DEPTH = 8            # nesting levels of entity-inside-entity
MAX_GROWTH = 64          # expanded size ceiling as a multiple of the original

_DECL_RE = re.compile(
    r"<!ENTITY\s+(?P<pct>%\s+)?(?P<name>[A-Za-z_:][-A-Za-z0-9._:]*)\s+"
    r"(?P<body>\"[^\"]*\"|'[^']*'|[^>]*?)\s*>",
    re.DOTALL,
)
_REF_RE = re.compile(r"&(?P<name>[A-Za-z_:][-A-Za-z0-9._:]*);")
_EXTERNAL_RE = re.compile(r"^\s*(SYSTEM|PUBLIC)\b", re.IGNORECASE)


class SvgEntityError(ValueError):
    """The document declares something we will not expand, or references
    something that was never declared."""


def _find_internal_subset(text: str):
    """Locate the internal DTD subset. Returns (start, end) indices spanning
    '[' .. ']' inclusive, or None. Scanned rather than regexed so that a ']'
    inside a quoted entity value cannot end it early."""
    m = re.search(r"<!DOCTYPE\b", text)
    if not m:
        return None
    i = m.end()
    n = len(text)
    while i < n:
        c = text[i]
        if c == ">":
            return None                       # DOCTYPE closed, no subset
        if c == "[":
            break
        if c in "\"'":                        # skip the quoted public/system id
            j = text.find(c, i + 1)
            if j < 0:
                raise SvgEntityError("unterminated quoted string in DOCTYPE")
            i = j + 1
            continue
        i += 1
    else:
        return None
    start = i
    i += 1
    while i < n:
        c = text[i]
        if c in "\"'":
            j = text.find(c, i + 1)
            if j < 0:
                raise SvgEntityError("unterminated quoted string in DTD subset")
            i = j + 1
            continue
        if c == "<" and text.startswith("<!--", i):
            j = text.find("-->", i)
            if j < 0:
                raise SvgEntityError("unterminated comment in DTD subset")
            i = j + 3
            continue
        if c == "]":
            return start, i
        i += 1
    raise SvgEntityError("unterminated internal DTD subset (no closing ']')")


def expand_internal_entities(text: str, *, source: str = "<svg>") -> tuple[str, dict]:
    """Resolve internal entity references and delete the internal DTD subset.

    Returns (rewritten_text, info). `info` records what happened so a caller can
    report it: {"declared": {...}, "expanded": {name: count}, "removed_subset":
    bool}. A document with no internal subset is returned byte-identical with
    expanded == {}.
    """
    info = {"declared": {}, "expanded": {}, "removed_subset": False}
    span = _find_internal_subset(text)
    if span is None:
        return text, info

    start, end = span
    subset = text[start + 1:end]

    decls: dict[str, str] = {}
    for m in _DECL_RE.finditer(subset):
        body = m.group("body").strip()
        name = m.group("name")
        if m.group("pct"):
            # A parameter entity (%foo;) drives DTD construction, not content.
            # We do not implement DTD assembly; refuse rather than half-do it.
            raise SvgEntityError(
                f"{source}: parameter entity '%{name};' is declared. This module "
                f"expands content entities only; the document needs a real DTD "
                f"processor.")
        if _EXTERNAL_RE.match(body):
            raise SvgEntityError(
                f"{source}: entity '{name}' is EXTERNAL ({body[:60]!r}). Fetching "
                f"it is the XXE vector this tool exists to avoid -- refusing. "
                f"Inline the value in the source SVG if it is really needed.")
        if len(body) >= 2 and body[0] == body[-1] and body[0] in "\"'":
            body = body[1:-1]
        decls[name] = body
    info["declared"] = dict(decls)

    # Resolve entity-inside-entity before touching the document body.
    for _ in range(MAX_DEPTH):
        changed = False
        for k, v in list(decls.items()):
            new = _REF_RE.sub(
                lambda m: decls.get(m.group("name"), m.group(0)), v)
            if new != v:
                decls[k] = new
                changed = True
        if not changed:
            break
    else:
        raise SvgEntityError(
            f"{source}: entity definitions still nest after {MAX_DEPTH} passes -- "
            f"refusing (possible billion-laughs).")

    body_text = text[:start] + text[end + 1:]
    # Drop the now-empty '[]' remains and tidy '<!DOCTYPE ... >'.
    body_text = re.sub(r"(<!DOCTYPE\b[^>\[]*)\s*>", r"\1>", body_text, count=1)

    limit = MAX_GROWTH * max(len(text), 1)
    counts: dict[str, int] = {}
    missing: set[str] = set()

    def _sub(m):
        name = m.group("name")
        if name in decls:
            counts[name] = counts.get(name, 0) + 1
            return decls[name]
        if name not in XML_BUILTINS:
            missing.add(name)
        return m.group(0)

    out = _REF_RE.sub(_sub, body_text)
    if len(out) > limit:
        raise SvgEntityError(
            f"{source}: entity expansion grew past {MAX_GROWTH}x the source "
            f"size -- refusing.")
    if missing:
        raise SvgEntityError(
            f"{source}: undeclared entity reference(s) {sorted(missing)}. "
            f"Expanding would silently change the artwork -- refusing.")

    info["expanded"] = counts
    info["removed_subset"] = True
    return out, info


def read_svg_bytes(path, *, encoding: str = "utf-8") -> tuple[bytes, dict]:
    """Read an SVG ready to hand to a hardened parser (cairosvg/defusedxml).

    Returns (bytes, info). Files without an internal subset -- the normal case,
    and every asset in this repo except the two Illustrator badges -- come back
    with their original bytes untouched.
    """
    raw = open(path, "rb").read()
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    out, info = expand_internal_entities(text, source=str(path))
    if not info["removed_subset"]:
        return raw, info
    return out.encode("utf-8"), info
