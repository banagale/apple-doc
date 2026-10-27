"""Locate Apple's documentation asset and build/inspect the keyword index over it.

Apple's database (``documentation-db/index.sql``) is a vector index built with a private
embedding model. This module keeps a separate, contentless SQLite FTS5 keyword index: it
stores only tokens and a little metadata, and search reads the page text back from Apple's
database, so excerpts always match Apple's content.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from apple_doc.errors import ASSET_NOT_FOUND, INDEX_PROBLEM, AppleDocError

DEFAULT_ASSET_GLOB = (
    "/System/Library/AssetsV2/com_apple_MobileAsset_AppleDeveloperDocumentation/"
    "*.asset/AssetData/documentation-db/index.sql"
)
DEFAULT_INDEX = "~/Library/Caches/apple-doc/fts.sqlite"

# Section anchors that are lists of links, not prose; indexing them only adds noise.
SKIP_ANCHORS = {
    "Relationships",
    "Resources",
    "Videos",
    "Change-log",
    "Related",
    "Developer-documentation",
    "See-Also",
}

REBUILD_HINT = (
    "apple-doc: the documentation asset changed since the index was built; "
    "run `apple-doc --build` to refresh it."
)


def asset_glob() -> str:
    return os.environ.get("APPLE_DOC_ASSET_GLOB") or DEFAULT_ASSET_GLOB


def index_path() -> str:
    return os.environ.get("APPLE_DOC_INDEX") or os.path.expanduser(DEFAULT_INDEX)


def newest_asset() -> str | None:
    """Path of the newest documentation database matching the asset glob, or None."""
    paths = sorted(glob.glob(asset_glob()), key=os.path.getmtime)
    return paths[-1] if paths else None


def asset_db() -> str:
    path = newest_asset()
    if not path:
        raise AppleDocError(
            "Apple documentation asset not found. Xcode downloads it; run "
            "`apple-doc --doctor` for details. Expected " + asset_glob(),
            ASSET_NOT_FOUND,
        )
    return path


def ro(path: str) -> sqlite3.Connection:
    """Open a SQLite file read-only without creating journals next to it."""
    # as_uri() percent-encodes '#', '?' and '%' so SQLite can't misread the filename.
    uri = Path(os.path.abspath(path)).as_uri() + "?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)


def unreadable_asset(path: str, err: Exception) -> AppleDocError:
    return AppleDocError(
        "documentation asset at %s is unreadable (%s); expected Apple's documentation-db "
        "SQLite file. Check APPLE_DOC_ASSET_GLOB or run `apple-doc --doctor`." % (path, err),
        ASSET_NOT_FOUND,
    )


def check_asset(path: str) -> int:
    """Number of documents in the asset; raises AppleDocError if it is not a usable database."""
    try:
        db = ro(path)
        try:
            db.execute("SELECT asset_id, document FROM documents LIMIT 1").fetchall()
            return db.execute("SELECT count(*) FROM documents").fetchone()[0]
        finally:
            db.close()
    except sqlite3.Error as e:
        raise unreadable_asset(path, e) from e


def _number_text(s: str) -> str:
    """A JSON number as text, so versions print as Apple wrote them ("10.10", "15.0").

    Apple's data also holds float artifacts such as 10.109999999999999 (meaning 10.11);
    those are collapsed to the shortest decimal that round-trips.
    """
    whole, _, frac = s.partition(".")
    if len(frac) >= 12 and "e" not in s.lower():
        return repr(float(s))
    return s


def load_doc(blob) -> dict | None:
    """Parse one document row; None if it is not the JSON object Apple's asset stores.

    Text fields are coerced to strings and platforms to a list of dicts, so a damaged or
    unexpected row can't crash the build, search or --full.
    """
    try:
        doc = json.loads(blob, parse_float=_number_text)
    except (ValueError, TypeError):  # includes UnicodeDecodeError
        return None
    if not isinstance(doc, dict):
        return None
    for k in ("title", "framework", "type", "content", "roleHeading"):
        if k in doc and not isinstance(doc[k], str):
            doc[k] = ""
    plats = doc.get("platforms")
    doc["platforms"] = [p for p in plats if isinstance(p, dict)] if isinstance(plats, list) else []
    return doc


def camel_parts(s: str) -> list[str]:
    return re.findall(r"[A-Z]+(?=[A-Z][a-z]|\d|\b)|[A-Z]?[a-z]+|[A-Z]+|\d+", s)


def ident_text(uri: str, title: str, content: str) -> str:
    """Identifier words for the uri path, title and declaration, joined and camel-split."""
    segs = [s for s in uri.split("#")[0].split("/")[2:] if s]
    names = segs + [title]
    m = re.search(r"```\n(.*?)```", content or "", re.S)
    decl = m.group(1)[:400] if m else ""
    out = []
    for n in names:
        out.append(re.sub(r"[^A-Za-z0-9]", "", n))  # noResponder(for:) -> noResponderfor
        for w in re.findall(r"[A-Za-z0-9]+", n):
            out.append(w)
            out.extend(camel_parts(w))
    for w in re.findall(r"[A-Za-z][A-Za-z0-9]+", decl):
        out.extend(camel_parts(w))
    if "#" in uri:
        out.extend(uri.split("#", 1)[1].split("-"))
    return " ".join(out)


def build() -> str:
    """(Re)build the keyword index from the newest asset. Returns a one-line summary."""
    src = asset_db()
    check_asset(src)
    index = index_path()
    if os.path.isdir(index):
        raise AppleDocError(
            "index path %s is a directory; point APPLE_DOC_INDEX at a file." % index,
            INDEX_PROBLEM,
        )
    if os.path.isfile(index) and os.path.getsize(index) > 0 and not _is_index(index):
        raise AppleDocError(
            "%s exists and is not an apple-doc index; refusing to overwrite it. "
            "Point APPLE_DOC_INDEX somewhere else or remove the file." % index,
            INDEX_PROBLEM,
        )
    t0 = time.time()
    tmp = None
    try:
        parent = os.path.dirname(index) or "."
        os.makedirs(parent, exist_ok=True)
        # A unique temp file per run, so concurrent builds don't collide.
        fd, tmp = tempfile.mkstemp(dir=parent, prefix=os.path.basename(index) + ".", suffix=".tmp")
        os.close(fd)
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(tmp, 0o666 & ~umask)  # mkstemp creates 0600; a cache file needn't be private
        n, skipped = _write_index(src, tmp)
        if n == 0:
            raise AppleDocError(
                "documentation asset at %s has no readable documents; index not replaced." % src,
                ASSET_NOT_FOUND,
            )
        os.replace(tmp, index)
        tmp = None
    except sqlite3.Error as e:
        raise AppleDocError("index build failed (%s)" % e, INDEX_PROBLEM) from e
    except OSError as e:
        raise AppleDocError("cannot write the index at %s (%s)" % (index, e), INDEX_PROBLEM) from e
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
    summary = "indexed %d docs from %s in %.0fs -> %s (%.0f MB)" % (
        n,
        src,
        time.time() - t0,
        index,
        os.path.getsize(index) / 1e6,
    )
    if skipped:
        summary += "; skipped %d unreadable rows" % skipped
    return summary


def _is_index(path: str) -> bool:
    try:
        db = ro(path)
        try:
            db.execute("SELECT v FROM info WHERE k='source'").fetchall()
            return True
        finally:
            db.close()
    except sqlite3.Error:
        return False


def _write_index(src: str, tmp: str) -> tuple[int, int]:
    s = ro(src)
    d = sqlite3.connect(tmp)
    d.executescript("""
      PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
      CREATE TABLE meta(id INTEGER PRIMARY KEY, uri TEXT, framework TEXT, type TEXT,
                        macos INTEGER);
      CREATE VIRTUAL TABLE fts USING fts5(title, ident, body, content='',
                                          tokenize='porter unicode61');
      CREATE TABLE info(k TEXT PRIMARY KEY, v TEXT);""")
    n = skipped = 0
    for aid, blob in s.execute("SELECT asset_id, document FROM documents"):
        if isinstance(aid, str) and "#" in aid and aid.split("#", 1)[1] in SKIP_ANCHORS:
            continue
        doc = load_doc(blob) if isinstance(aid, str) and aid.startswith("/") else None
        if doc is None:
            skipped += 1
            continue
        content = doc.get("content") or ""
        title = doc.get("title") or aid.rsplit("/", 1)[-1]
        plats = doc.get("platforms") or []
        # 1 = available on macOS, 0 = other platforms only, 2 = no platform data
        macos = 1 if any(p.get("platform") == "macOS" for p in plats) else (0 if plats else 2)
        n += 1
        d.execute(
            "INSERT INTO meta VALUES(?,?,?,?,?)",
            (n, aid, doc.get("framework") or "", doc.get("type") or "", macos),
        )
        d.execute(
            "INSERT INTO fts(rowid,title,ident,body) VALUES(?,?,?,?)",
            (n, title, ident_text(aid, title, content), content),
        )
    d.execute("CREATE INDEX meta_fw ON meta(framework COLLATE NOCASE)")
    d.execute(
        "INSERT INTO info VALUES('source',?),('mtime',?),('docs',?)",
        (src, str(os.path.getmtime(src)), str(n)),
    )
    d.execute("INSERT INTO fts(fts) VALUES('optimize')")
    d.commit()
    d.close()
    s.close()
    return n, skipped


@dataclass
class IndexState:
    path: str
    source: str  # asset path recorded at build time
    mtime: str  # asset mtime recorded at build time
    docs: int
    current: str | None  # newest asset on disk now, if any

    @property
    def stale(self) -> bool:
        """True when the asset on disk is not the one the index was built from."""
        if self.current is None:
            return not os.path.exists(self.source)
        if self.current != self.source:
            return True
        return str(os.path.getmtime(self.current)) != self.mtime


def open_index() -> tuple[sqlite3.Connection, IndexState]:
    path = index_path()
    if not os.path.exists(path):
        raise AppleDocError(
            "no index yet at %s; run `apple-doc --build` once (seconds to a few minutes, "
            "offline), or point APPLE_DOC_INDEX at an existing index." % path,
            INDEX_PROBLEM,
        )
    if os.path.isdir(path):
        raise AppleDocError(
            "index path %s is a directory; point APPLE_DOC_INDEX at a file." % path,
            INDEX_PROBLEM,
        )
    try:
        idx = ro(path)
        info = dict(idx.execute("SELECT k, v FROM info").fetchall())
        # The tables search needs, so a damaged index fails here with one clear message.
        idx.execute("SELECT id, uri, framework, type, macos FROM meta LIMIT 1").fetchall()
        idx.execute("SELECT rowid FROM fts LIMIT 0").fetchall()
        docs = int(info.get("docs") or 0)
        if not isinstance(info.get("source"), str) or not info["source"]:
            raise ValueError("no source asset recorded")
    except (sqlite3.Error, ValueError, TypeError) as e:
        raise index_unreadable(path, e) from e
    state = IndexState(
        path=path,
        source=info["source"],
        mtime=str(info.get("mtime", "")),
        docs=docs,
        current=newest_asset(),
    )
    return idx, state


def index_unreadable(path: str, err: Exception) -> AppleDocError:
    return AppleDocError(
        "index at %s is unreadable (%s); run `apple-doc --build`." % (path, err), INDEX_PROBLEM
    )
