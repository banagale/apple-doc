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
import time
from dataclasses import dataclass

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
    return sqlite3.connect("file:%s?mode=ro&immutable=1" % path, uri=True)


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
            return db.execute("SELECT count(*) FROM documents").fetchone()[0]
        finally:
            db.close()
    except sqlite3.Error as e:
        raise unreadable_asset(path, e) from e


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
    index = index_path()
    os.makedirs(os.path.dirname(index) or ".", exist_ok=True)
    tmp = index + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    t0 = time.time()
    try:
        n = _write_index(src, tmp)
    except BaseException as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        if isinstance(e, sqlite3.Error):
            raise AppleDocError("index build failed (%s)" % e, INDEX_PROBLEM) from e
        raise
    os.replace(tmp, index)
    return "indexed %d docs from %s in %.0fs -> %s (%.0f MB)" % (
        n,
        src,
        time.time() - t0,
        index,
        os.path.getsize(index) / 1e6,
    )


def _write_index(src: str, tmp: str) -> int:
    s = ro(src)
    try:
        s.execute("SELECT asset_id, document FROM documents LIMIT 1").fetchall()
    except sqlite3.Error as e:
        s.close()
        raise unreadable_asset(src, e) from e
    d = sqlite3.connect(tmp)
    d.executescript("""
      PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
      CREATE TABLE meta(id INTEGER PRIMARY KEY, uri TEXT, framework TEXT, type TEXT,
                        macos INTEGER);
      CREATE VIRTUAL TABLE fts USING fts5(title, ident, body, content='',
                                          tokenize='porter unicode61');
      CREATE TABLE info(k TEXT PRIMARY KEY, v TEXT);""")
    n = 0
    for aid, blob in s.execute("SELECT asset_id, document FROM documents"):
        if "#" in aid and aid.split("#", 1)[1] in SKIP_ANCHORS:
            continue
        try:
            doc = json.loads(blob)
        except Exception:
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
    return n


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
            "no index yet; run `apple-doc --build` once (seconds to a few minutes, offline).",
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
    except sqlite3.Error as e:
        raise AppleDocError(
            "index at %s is unreadable (%s); run `apple-doc --build`." % (path, e),
            INDEX_PROBLEM,
        ) from e
    state = IndexState(
        path=path,
        source=info.get("source", ""),
        mtime=info.get("mtime", ""),
        docs=int(info.get("docs") or 0),
        current=newest_asset(),
    )
    return idx, state
