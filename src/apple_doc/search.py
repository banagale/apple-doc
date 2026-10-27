"""Keyword search over the index, re-ranked with page text read from Apple's database."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field

from apple_doc.errors import PAGE_NOT_FOUND, USAGE, AppleDocError
from apple_doc.index import asset_db, camel_parts, open_index, ro
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
            "empty query (only stopwords or punctuation); pass API names or topic words",
            USAGE,
        )
    idx, state = open_index()
    src = state.source if os.path.exists(state.source) else asset_db()
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
    cands = idx.execute(sql, params).fetchall()
    wl = [w.lower() for w in words]
    ranked = []
    for _cid, uri, fw, typ, macos, r in cands:
        row = docs.execute("SELECT document FROM documents WHERE asset_id=?", (uri,)).fetchone()
        if not row:
            continue
        doc = json.loads(row[0])
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
            score += {1: 1.0, 0: -4.0, 2: 0.0}[macos]
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
    idx.close()
    docs.close()
    return SearchResult(
        query=query,
        hits=hits,
        candidates=len(cands),
        seconds=time.time() - t0,
        stale=state.stale,
        terms=terms,
    )


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
    return "\n".join(out[:max_lines])


@dataclass
class Page:
    uri: str
    title: str
    framework: str
    lines: list[str]


def get_page(uri: str) -> Page:
    """One page or section by its documentation path or developer.apple.com URL."""
    uri = uri.replace(WEB, "")
    docs = ro(asset_db())
    row = docs.execute(
        "SELECT asset_id, document FROM documents WHERE asset_id=?", (uri,)
    ).fetchone()
    if not row:
        row = docs.execute(
            "SELECT asset_id, document FROM documents WHERE asset_id=? COLLATE NOCASE", (uri,)
        ).fetchone()
    docs.close()
    if not row:
        raise AppleDocError(
            "no page " + uri + " (pass a path such as /documentation/AppKit/NSView, "
            "as printed under each search hit)",
            PAGE_NOT_FOUND,
        )
    doc = json.loads(row[1])
    return Page(
        uri=row[0],
        title=doc.get("title") or "",
        framework=doc.get("framework") or "",
        lines=page_lines(doc.get("content") or ""),
    )


def format_page(page: Page, max_lines: int) -> str:
    out = page.lines[:max_lines]
    if len(page.lines) > max_lines:
        out.append("... (%d more lines)" % (len(page.lines) - max_lines))
    return "\n".join(out)
