"""Keyword search over the index, re-ranked with page text read from Apple's database."""

from __future__ import annotations

import difflib
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from urllib.parse import unquote

from apple_doc.errors import ASSET_NOT_FOUND, INDEX_PROBLEM, PAGE_NOT_FOUND, USAGE, AppleDocError
from apple_doc.index import (
    SKIP_ANCHORS,
    asset_db,
    camel_parts,
    index_unreadable,
    load_doc,
    open_index,
    ro,
    unreadable_asset,
)
from apple_doc.render import WEB, avail, excerpt, page_lines

STOP = set(
    "a an the of to in on for and or with how does do is are be by from at as it this that "
    "what when why which into via use using vs not".split()
)
CANDIDATES = 400


@dataclass
class Hit:
    rank: int
    title: str
    framework: str
    role: str
    availability: str
    uri: str
    excerpt: list[str]
    score: float

    @property
    def url(self) -> str:
        return WEB + self.uri


@dataclass
class SearchResult:
    query: str
    hits: list[Hit]
    candidates: int
    seconds: float
    stale: bool
    terms: list[str] = field(default_factory=list)


def query_terms(q: str) -> tuple[list[str], list[str]]:
    """The query's non-stopword words, and those words plus their camelCase parts."""
    words = [w for w in re.findall(r"[A-Za-z0-9_]+", q) if w.lower() not in STOP]
    terms = []
    for w in words:
        terms.append(w.lower())
        terms.extend(p.lower() for p in camel_parts(w) if len(p) > 2 and p.lower() not in STOP)
    seen: list[str] = []
    for t in terms:
        if t not in seen:
            seen.append(t)
    return words, seen


def search(
    query: str,
    framework: str | None = None,
    limit: int = 3,
    lines: int = 4,
    any_platform: bool = False,
) -> SearchResult:
    t0 = time.time()
    words, terms = query_terms(query)
    if not terms:
        raise AppleDocError(
            "no searchable words in the query (stopwords, punctuation and non-ASCII text are "
            "ignored); pass API names or English topic words",
            USAGE,
        )
    idx, state = open_index()
    if framework is not None:
        try:
            framework = resolve_framework(idx, framework)
        except sqlite3.Error as e:
            idx.close()
            raise index_unreadable(state.path, e) from e
    src = state.source if os.path.exists(state.source) else asset_db()
    try:
        return _search(
            idx, src, state, query, words, terms, framework, limit, lines, any_platform, t0
        )
    except sqlite3.Error as e:
        raise unreadable_asset(src, e) from e
    finally:
        idx.close()


def _search(idx, src, state, query, words, terms, framework, limit, lines, any_platform, t0):
    docs = ro(src)
    match = " OR ".join('"%s"' % t.replace('"', "") for t in terms)
    sql = (
        "SELECT m.id, m.uri, m.framework, m.type, m.macos, bm25(fts, 8.0, 4.0, 1.0) AS r "
        "FROM fts JOIN meta m ON m.id = fts.rowid WHERE fts MATCH ?"
    )
    params: list = [match]
    if framework:
        sql += " AND m.framework = ? COLLATE NOCASE"
        params.append(framework)
    sql += " ORDER BY r LIMIT %d" % CANDIDATES
    try:
        cands = idx.execute(sql, params).fetchall()
    except sqlite3.Error as e:
        raise AppleDocError(
            "index at %s is unreadable (%s); run `apple-doc --build`." % (state.path, e),
            INDEX_PROBLEM,
        ) from e
    wl = [w.lower() for w in words]
    ranked = []
    for _cid, uri, fw, typ, macos, r in cands:
        row = docs.execute("SELECT document FROM documents WHERE asset_id=?", (uri,)).fetchone()
        if not row:
            continue
        doc = load_doc(row[0])
        if doc is None:
            continue
        content = doc.get("content") or ""
        low = content.lower()
        path = uri.lower()
        last = re.sub(r"[^a-z0-9]", "", path.split("#")[0].rsplit("/", 1)[-1])
        cover = sum(1 for w in wl if w in low or w in path)
        score = -r + 6.0 * cover / max(1, len(wl))
        score += sum(4.0 for w in wl if len(w) > 3 and (last == w or last.startswith(w)))
        if "#" not in uri and any(last == w for w in wl):
            score += 3.0  # the page itself before its sections
        score += sum(1.5 for w in wl if "/" + w in path)
        if not any_platform:
            score += {1: 1.0, 0: -4.0, 2: 0.0}.get(macos, 0.0)
        if typ == "topic":
            score -= 1.0
        ranked.append((score, uri, fw, doc))
    ranked.sort(key=lambda x: -x[0])
    hits = []
    for n, (score, uri, fw, doc) in enumerate(ranked[: max(0, limit)], 1):
        hits.append(
            Hit(
                rank=n,
                title=doc.get("title") or "",
                framework=fw,
                role=doc.get("roleHeading") or "",
                availability=avail(doc),
                uri=uri,
                excerpt=excerpt(doc.get("content") or "", terms, lines),
                score=round(score, 3),
            )
        )
    docs.close()
    return SearchResult(
        query=query,
        hits=hits,
        candidates=len(cands),
        seconds=time.time() - t0,
        stale=state.stale,
        terms=terms,
    )


def list_frameworks() -> list[tuple[str, int]]:
    """Framework names in the index with their document counts."""
    idx, state = open_index()
    try:
        return idx.execute(
            "SELECT framework, count(*) FROM meta WHERE framework <> '' "
            "GROUP BY framework COLLATE NOCASE ORDER BY framework COLLATE NOCASE"
        ).fetchall()
    except sqlite3.Error as e:
        raise index_unreadable(state.path, e) from e
    finally:
        idx.close()


def resolve_framework(idx: sqlite3.Connection, name: str) -> str:
    """The name as given if the index knows it (any case); otherwise a usage error with hints."""
    name = name.strip()
    if not name:
        raise AppleDocError("--framework needs a name, e.g. -f AppKit", USAGE)
    if idx.execute(
        "SELECT 1 FROM meta WHERE framework = ? COLLATE NOCASE LIMIT 1", (name,)
    ).fetchone():
        return name
    names = [r[0] for r in idx.execute("SELECT DISTINCT framework FROM meta WHERE framework <> ''")]
    low = name.lower()
    hints = [n for n in names if low in n.lower()]
    hints += [n for n in names if "".join(w[0] for w in n.split()).lower() == low]
    by_lower = {n.lower(): n for n in names}
    hints += [by_lower[m] for m in difflib.get_close_matches(low, list(by_lower), n=3)]
    hints = list(dict.fromkeys(hints))[:5]
    msg = "unknown framework %r" % name
    if hints:
        msg += "; did you mean: " + ", ".join(hints)
    raise AppleDocError(msg + " (apple-doc --list-frameworks shows all)", USAGE)


def format_search(res: SearchResult, max_lines: int) -> str:
    out = []
    for h in res.hits:
        hdr = "%d. %s  [%s%s%s]" % (
            h.rank,
            h.title,
            h.framework,
            (", " + h.role) if h.role else "",
            (", " + h.availability) if h.availability else "",
        )
        out.append(hdr)
        for ln in h.excerpt:
            out.append("   " + ln)
        out.append("   " + h.url)
        out.append("")
    if not res.hits:
        out.append("no hits for: " + res.query)
    out.append(
        "(%d candidates, %.2fs; full page: apple-doc --full URI)" % (res.candidates, res.seconds)
    )
    if len(out) > max_lines:
        out = out[: max_lines - 1] + [
            "... (output capped at %d lines; lower -n/--lines or raise --max-lines)" % max_lines
        ]
    return "\n".join(out)


@dataclass
class Page:
    uri: str
    title: str
    framework: str
    lines: list[str]
    availability: str = ""
    sections: list[str] = field(default_factory=list)  # anchors of the page's sections


SECTIONS_SHOWN = 40


def page_sections(docs: sqlite3.Connection, page_uri: str) -> list[str]:
    """Section anchors stored for a page (Apple keeps each section as its own row)."""
    base = page_uri.split("#")[0]
    rows = docs.execute(
        "SELECT asset_id FROM documents WHERE asset_id > ? AND asset_id < ? ORDER BY rowid",
        (base + "#", base + "$"),
    ).fetchall()
    anchors = [r[0].split("#", 1)[1] for r in rows]
    return [a for a in anchors if a not in SKIP_ANCHORS]


def normalize_uri(uri: str) -> str:
    """Accept a /documentation/... or /design/... path, or a developer.apple.com URL."""
    uri = uri.strip()
    uri = re.sub(r"^https?://(www\.)?developer\.apple\.com", "", uri, flags=re.I)
    uri = re.sub(r"\?[^#]*", "", uri)  # ?language=objc and the like
    path, sep, frag = uri.partition("#")
    path, frag = unquote(path), unquote(frag)  # copied URLs encode ( ) : and spaces
    path = path.rstrip("/")
    if path and not path.startswith("/"):
        path = "/" + path
    return path + sep + frag


def get_page(uri: str) -> Page:
    """One page or section by its path, its URL, or (if unique) its last path segment."""
    given = uri
    uri = normalize_uri(uri)
    if not uri:
        raise AppleDocError("--full needs a path, e.g. /documentation/AppKit/NSView", USAGE)
    src = asset_db()
    try:
        docs = ro(src)
        q = "SELECT asset_id, document FROM documents WHERE asset_id=?"
        row = docs.execute(q, (uri,)).fetchone()
        if not row:
            row = docs.execute(q + " COLLATE NOCASE", (uri,)).fetchone()
        if not row:
            try:
                row = _by_last_segment(docs, uri, given)
            except AppleDocError as e:
                if "#" in uri:
                    page = uri.split("#")[0]
                    base = docs.execute(q + " COLLATE NOCASE", (page,)).fetchone()
                    if not base:
                        try:
                            base = _by_last_segment(docs, page, page)
                        except AppleDocError:
                            base = None
                    if base:
                        anchors = page_sections(docs, base[0])
                        e.args = (
                            "no section #%s on %s; its sections: %s"
                            % (uri.split("#", 1)[1], base[0], " ".join("#" + a for a in anchors)),
                        )
                raise
        doc = load_doc(row[1])
        if doc is None:
            raise AppleDocError(
                "page %s exists but its stored content is unreadable" % row[0], ASSET_NOT_FOUND
            )
        sections = [] if "#" in row[0] else page_sections(docs, row[0])
        docs.close()
    except sqlite3.Error as e:
        raise unreadable_asset(src, e) from e
    return Page(
        uri=row[0],
        title=doc.get("title") or "",
        framework=doc.get("framework") or "",
        lines=page_lines(doc.get("content") or ""),
        availability=avail(doc),
        sections=sections,
    )


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _by_last_segment(docs: sqlite3.Connection, uri: str, given: str):
    """Find a page by its final path segment, e.g. an article slug under another framework."""
    path, _, frag = uri.partition("#")
    seg = path.rsplit("/", 1)[-1]
    rows = []
    if seg and len(uri) <= 2000:
        want = "/" + seg.lower() + (("#" + frag.lower()) if frag else "")
        like = "%/" + _like_escape(seg) + ("#" + _like_escape(frag) if frag else "")
        rows = [
            r
            for r in docs.execute(
                "SELECT asset_id, document FROM documents WHERE asset_id LIKE ? ESCAPE '\\'",
                (like,),
            )
            if r[0].lower().endswith(want)
        ]
    if len(rows) == 1:
        return rows[0]
    msg = "no page " + given
    if rows:
        msg += "; %d pages end that way, e.g. %s" % (
            len(rows),
            ", ".join(sorted(r[0] for r in rows)[:5]),
        )
    else:
        msg += " (pass a path such as /documentation/AppKit/NSView, as printed under each hit)"
    raise AppleDocError(msg, PAGE_NOT_FOUND)


def format_page(page: Page, max_lines: int) -> str:
    out = page.lines[:max_lines]
    if len(page.lines) > max_lines:
        out.append("... (%d more lines)" % (len(page.lines) - max_lines))
    if page.availability or page.sections:
        out.append("")
    if page.availability:
        out.append("availability: " + page.availability)
    if page.sections:
        out.append(
            "%d section%s, each its own page: apple-doc --full '%s#ANCHOR'"
            % (len(page.sections), "" if len(page.sections) == 1 else "s", page.uri)
        )
        out.extend("  #" + a for a in page.sections[:SECTIONS_SHOWN])
        if len(page.sections) > SECTIONS_SHOWN:
            out.append(
                "  ... and %d more (--json lists all)" % (len(page.sections) - SECTIONS_SHOWN)
            )
    return "\n".join(out)
