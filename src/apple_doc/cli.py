"""apple-doc command line: search, --full, --build, --doctor."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict

from apple_doc import __version__
from apple_doc.errors import (
    ASSET_NOT_FOUND,
    INDEX_PROBLEM,
    NO_HITS,
    OK,
    AppleDocError,
)
from apple_doc.index import (
    REBUILD_HINT,
    asset_glob,
    build,
    index_path,
    newest_asset,
    open_index,
)
from apple_doc.search import format_page, format_search, get_page, search

FULL_LINES = 80

DESCRIPTION = """\
Search Apple's developer documentation offline: API reference for every framework,
declarations, availability, articles and the Human Interface Guidelines. Reads the copy of
the documentation that macOS downloads for Xcode; no network, no Xcode process.

The search is keyword-based: pass API names and the words Apple's pages use, not sentences.
Results prefer symbols available on macOS (see --any-platform)."""

EPILOG = """\
examples:
  apple-doc --build                                  build the index (once, and after updates)
  apple-doc NSTextView undo -f AppKit                class and member names work best
  apple-doc loadHTMLString baseURL relative -f WebKit -n 5
  apple-doc toolbars -f "Human Interface Guidelines" --any-platform
  apple-doc --full '/documentation/AppKit/NSResponder/noResponder(for:)'  (quote it)
  apple-doc --json NSWindow becomeKey | jq '.hits[].uri'

exit codes:
  0  success            1  no hits             2  usage error (bad flags, empty query)
  3  documentation asset not found (Xcode has not downloaded it)
  4  index missing or unreadable (run apple-doc --build); --doctor also uses 4 for a stale index
  5  page not found (--full)

environment:
  APPLE_DOC_INDEX       index file (default ~/Library/Caches/apple-doc/fts.sqlite)
  APPLE_DOC_ASSET_GLOB  glob for Apple's documentation-db/index.sql"""


def positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("%r is not a whole number" % value) from None
    if n < 1:
        raise argparse.ArgumentTypeError("must be 1 or more, got %d" % n)
    return n


def make_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="apple-doc",
        usage="apple-doc [options] QUERY...\n       apple-doc --full URI | --build | --doctor",
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("query", nargs="*", metavar="QUERY", help="API names and topic words")
    ap.add_argument(
        "--framework",
        "-f",
        metavar="NAME",
        help="restrict to one framework, e.g. AppKit, WebKit, Foundation, SwiftUI, "
        '"Human Interface Guidelines" (case-insensitive)',
    )
    ap.add_argument(
        "--limit",
        "-n",
        type=positive_int,
        default=3,
        metavar="N",
        help="number of hits to show (default 3)",
    )
    ap.add_argument(
        "--lines",
        type=positive_int,
        default=4,
        metavar="N",
        help="matching body lines per hit (default 4)",
    )
    ap.add_argument(
        "--any-platform", action="store_true", help="do not prefer macOS-available symbols"
    )
    ap.add_argument(
        "--max-lines",
        type=positive_int,
        default=60,
        metavar="N",
        help="cap on total output lines for a search (default 60)",
    )
    ap.add_argument(
        "--full",
        metavar="URI",
        help="print one whole page or section (first %d lines); URI is the "
        "/documentation/... path or developer.apple.com URL shown under a hit" % FULL_LINES,
    )
    ap.add_argument(
        "--json", action="store_true", help="machine-readable output for a search or --full"
    )
    ap.add_argument(
        "--build",
        action="store_true",
        help="(re)build the keyword index; run once, and after macOS/Xcode "
        "updates replace the documentation",
    )
    ap.add_argument(
        "--doctor",
        action="store_true",
        help="check the documentation asset and the index, then exit",
    )
    ap.add_argument("--version", action="version", version="%(prog)s " + __version__)
    return ap


def doctor() -> int:
    code = OK
    asset = newest_asset()
    if asset:
        print("asset:   ok     %s" % asset)
    else:
        print("asset:   MISSING  nothing matches %s" % asset_glob())
        print("         Open Xcode and let it finish downloading its components, then rerun.")
        code = ASSET_NOT_FOUND
    path = index_path()
    if not os.path.exists(path):
        print("index:   MISSING  %s (run `apple-doc --build`)" % path)
        return code or INDEX_PROBLEM
    try:
        idx, state = open_index()
        idx.close()
    except AppleDocError as e:
        print("index:   BROKEN   %s" % e)
        return code or e.code
    size = os.path.getsize(path) / 1e6
    print("index:   ok     %s (%d docs, %.0f MB)" % (path, state.docs, size))
    print("built from:     %s" % state.source)
    if state.stale:
        print("index:   STALE  " + REBUILD_HINT.removeprefix("apple-doc: "))
        return code or INDEX_PROBLEM
    return code


def run(argv: list[str] | None = None) -> int:
    ap = make_parser()
    a = ap.parse_args(argv)
    modes = [m for m in ("build", "doctor") if getattr(a, m)] + (["full"] if a.full else [])
    if len(modes) > 1:
        ap.error("choose one of --build, --doctor, --full")
    if modes and a.query:
        ap.error("--%s takes no QUERY words (got: %s)" % (modes[0], " ".join(a.query)))
    if a.build:
        print(build())
        return OK
    if a.doctor:
        return doctor()
    if a.full:
        page = get_page(a.full)
        if a.json:
            print(json.dumps(asdict(page), indent=2))
        else:
            print(format_page(page, FULL_LINES))
        return OK
    if not a.query:
        ap.error("QUERY required (or one of --build, --doctor, --full URI)")
    res = search(" ".join(a.query), a.framework, a.limit, a.lines, a.any_platform)
    if res.stale:
        print(REBUILD_HINT, file=sys.stderr)
    if a.json:
        data = {
            "query": res.query,
            "terms": res.terms,
            "candidates": res.candidates,
            "seconds": round(res.seconds, 3),
            "stale_index": res.stale,
            "hits": [dict(asdict(h), url=h.url) for h in res.hits],
        }
        print(json.dumps(data, indent=2))
    else:
        print(format_search(res, a.max_lines))
    return OK if res.hits else NO_HITS


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except AppleDocError as e:
        print("apple-doc: %s" % e, file=sys.stderr)
        return e.code
    except BrokenPipeError:
        # e.g. `apple-doc ... | head`; quiet exit like other Unix tools
        sys.stderr.close()
        return OK
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
