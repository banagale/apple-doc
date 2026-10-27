"""apple-doc command line: search, --full, --build, --doctor, --install-skill."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import asdict

from apple_doc import __version__
from apple_doc.errors import (
    ASSET_NOT_FOUND,
    INDEX_PROBLEM,
    NO_HITS,
    NOT_INSTALLED,
    OK,
    AppleDocError,
)
from apple_doc.index import (
    REBUILD_HINT,
    asset_glob,
    build,
    check_asset,
    index_path,
    newest_asset,
    open_index,
)
from apple_doc.search import format_page, format_search, get_page, list_frameworks, search
from apple_doc.skill import install, skill_text, target_dirs

FULL_LINES = 80

DESCRIPTION = """\
Look up Apple's developer documentation offline, in output sized for AI coding agents:
API reference for every framework, declarations, availability, articles and the Human
Interface Guidelines, read from the copy macOS downloads for Xcode. No network, no Xcode
process: any agent with a shell can run it, and --mcp serves clients that only take MCP.

The search is keyword-based: pass API names and the words Apple's pages use, not sentences.
Results prefer symbols available on macOS (see --any-platform). Put "--" before a query
that starts with "-", e.g. apple-doc -- -initWithFrame."""

EPILOG = """\
examples:
  apple-doc --build                                  build the index (once, and after updates)
  apple-doc --install-skill                          give Claude Code / Codex the skill
  apple-doc NSTextView undo -f AppKit                class and member names work best
  apple-doc loadHTMLString baseURL relative -f WebKit -n 5
  apple-doc toolbars -f "Human Interface Guidelines"
  apple-doc --full '/documentation/AppKit/NSResponder/noResponder(for:)'  (quote it)
  apple-doc --json NSWindow becomeKey | jq '.hits[].uri'

exit codes:
  0  success            1  no hits             2  usage error (bad flags, empty query,
                                                    unknown --framework)
  3  documentation asset not found or unreadable (Xcode has not downloaded it)
  4  index missing or unreadable (run apple-doc --build); --doctor also uses 4 for a stale index
  5  page not found (--full)
  6  --install-skill left a file alone (different SKILL.md or a symlink; see --force)

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


class Parser(argparse.ArgumentParser):
    def error(self, message: str):
        if "unrecognized arguments: -" in message:
            message += ' (put "--" before a query that starts with "-")'
        super().error(message)


def make_parser() -> argparse.ArgumentParser:
    ap = Parser(
        prog="apple-doc",
        usage="apple-doc [options] QUERY...\n"
        "       apple-doc --full URI | --build | --doctor | --list-frameworks\n"
        "       apple-doc --install-skill [--agent claude|codex|all] [--dir PATH] [--force]\n"
        "       apple-doc --mcp",
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    ap.add_argument("query", nargs="*", metavar="QUERY", help="API names and topic words")
    ap.add_argument(
        "--framework",
        "-f",
        metavar="NAME",
        help="restrict to one framework, e.g. AppKit, WebKit, Foundation, SwiftUI, "
        '"Human Interface Guidelines" (case-insensitive; see --list-frameworks)',
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
        help="matching body lines per hit, shown after its summary and declaration (default 4)",
    )
    ap.add_argument(
        "--any-platform", action="store_true", help="do not prefer macOS-available symbols"
    )
    ap.add_argument(
        "--max-lines",
        type=positive_int,
        default=60,
        metavar="N",
        help="cap on total output lines for a text search (default 60)",
    )
    ap.add_argument(
        "--full",
        metavar="URI",
        help="print one whole page or section (first %d lines); URI is the path "
        "(/documentation/... or /design/...) or developer.apple.com URL shown under a hit"
        % FULL_LINES,
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="JSON output for a search, --full (whole page) or --list-frameworks",
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
    ap.add_argument(
        "--list-frameworks",
        action="store_true",
        help="list the framework names --framework accepts, with page counts",
    )
    ap.add_argument(
        "--install-skill",
        action="store_true",
        help="install the agent skill (SKILL.md) for Claude Code (~/.claude/skills) and/or "
        "Codex (~/.agents/skills); default: whichever of ~/.claude, ~/.agents exists",
    )
    ap.add_argument(
        "--agent",
        choices=["claude", "codex", "all"],
        help="with --install-skill: which agent to install for",
    )
    ap.add_argument(
        "--dir",
        metavar="PATH",
        help="with --install-skill: write SKILL.md into this folder instead "
        "(another agent's skills dir)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="with --install-skill: replace a different SKILL.md, or write through a symlink",
    )
    ap.add_argument(
        "--print-skill", action="store_true", help="print the agent skill (SKILL.md) to stdout"
    )
    ap.add_argument(
        "--mcp",
        action="store_true",
        help="run as an MCP server over stdio (tools: search_apple_docs, read_apple_doc, "
        "list_frameworks), for clients that only take MCP",
    )
    ap.add_argument("--version", "-V", action="version", version="%(prog)s " + __version__)
    return ap


def doctor() -> int:
    code = OK
    asset = newest_asset()
    if asset:
        try:
            n = check_asset(asset)
            if n:
                print("asset:   ok     %s (%d documents)" % (asset, n))
            else:
                print("asset:   EMPTY  %s has no documents" % asset)
                code = ASSET_NOT_FOUND
        except AppleDocError as e:
            print("asset:   UNREADABLE  %s" % e)
            code = ASSET_NOT_FOUND
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
        try:
            check = idx.execute("PRAGMA quick_check").fetchone()[0]
        except sqlite3.Error as e:
            check = str(e)
        idx.close()
        if check != "ok":
            raise AppleDocError(
                "index at %s is damaged (%s); run `apple-doc --build`." % (path, check),
                INDEX_PROBLEM,
            )
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
    names = ("build", "doctor", "list_frameworks", "install_skill", "print_skill", "mcp")
    modes = [m for m in names if getattr(a, m)]
    modes += ["full"] if a.full is not None else []
    modes = [m.replace("_", "-") for m in modes]
    if len(modes) > 1:
        ap.error(
            "choose one of --build, --doctor, --full, --list-frameworks, --install-skill, "
            "--print-skill, --mcp"
        )
    if modes and a.query:
        ap.error("--%s takes no QUERY words (got: %s)" % (modes[0], " ".join(a.query)))
    if a.json and (a.build or a.doctor or a.install_skill or a.print_skill or a.mcp):
        ap.error("--json works with a search, --full or --list-frameworks")
    if not a.install_skill and (a.agent or a.dir is not None or a.force):
        ap.error("--agent, --dir and --force go with --install-skill")
    if a.print_skill:
        sys.stdout.write(skill_text())
        return OK
    if a.mcp:
        from apple_doc.mcp import serve

        return serve()
    if a.install_skill:
        outcomes = [install(d, a.force) for d in target_dirs(a.agent, a.dir)]
        for o in outcomes:
            print(o.line())
        if all(o.ok for o in outcomes):
            print("apple-doc %s skill installed; restart the agent to pick it up." % __version__)
            return OK
        return NOT_INSTALLED
    if a.list_frameworks:
        rows = list_frameworks()
        if a.json:
            print(json.dumps([{"framework": f, "pages": n} for f, n in rows], indent=2))
        else:
            for f, n in rows:
                print("%7d  %s" % (n, f))
        return OK
    if a.build:
        print(build())
        return OK
    if a.doctor:
        return doctor()
    if a.full is not None:
        page = get_page(a.full)
        if a.json:
            print(json.dumps(asdict(page), indent=2))
        else:
            print(format_page(page, FULL_LINES))
        return OK
    if not a.query:
        ap.error("QUERY required (or one of --build, --doctor, --full URI, --list-frameworks)")
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
    if sys.stdout is None:  # stdout closed (e.g. `apple-doc ... >&-`)
        sys.stdout = open(os.devnull, "w")
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
