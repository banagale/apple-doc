# apple-doc

Search Apple's developer documentation offline, from the copy macOS already keeps on disk.

```console
$ apple-doc loadHTMLString baseURL relative -f WebKit -n 1
1. loadHTMLString(_:baseURL:)  [WebKit, Instance Method, macOS 10.1+]
   Instance Method of WKWebView
   Loads the contents of the specified HTML string and navigates to it.
     func loadHTMLString(_ string: String, baseURL: URL?) -> WKNavigation?
   `string`
   `baseURL`
   The base URL to use when the system resolves relative URLs within the HTML string.
   Use this method to navigate to a webpage that you loaded or created yourself. For example, you might use this method to load HTML content that your app generates programmatically.
   https://developer.apple.com/documentation/WebKit/WKWebView/loadHTMLString(_:baseURL:)

(390 candidates, 0.02s; full page: apple-doc --full URI)
```

## What it is and why

Recent Xcode releases download Apple's entire developer documentation (about 263,000 pages and
sections: API reference for every framework, articles, sample-code pages and the Human Interface
Guidelines) as a SQLite database under `/System/Library/AssetsV2/`. Xcode's own
`DocumentationSearch` tool reads it, but that tool lives inside Xcode. Agents running outside
Xcode, such as Claude Code or Codex in a terminal, headless CI jobs or a local model, aren't
offered it.

`apple-doc` reads the same file directly. It is one command with no runtime dependencies beyond
Python's standard library. It never touches the network and never starts Xcode. A query takes
0.04 to 0.2 seconds. Each hit shows the title, framework, macOS availability, the declaration,
the lines that best match your query, and the developer.apple.com URL, so an agent can check how
an API behaves before writing code against it.

## Requirements

- **macOS with Apple's developer documentation asset downloaded.** apple-doc is tested on
  macOS 27 with Xcode 27. Xcode 26.3 and later are reported to download the same asset.
- **Python 3.11 or later.** `uv` installs one for you if needed.

Check whether the asset is there:

```bash
ls /System/Library/AssetsV2/com_apple_MobileAsset_AppleDeveloperDocumentation/*.asset/AssetData/documentation-db/index.sql
# or, after installing:
apple-doc --doctor
```

If it's missing, install Xcode from the App Store or developer.apple.com and open it. macOS
then downloads the documentation in the background through its asset service. The download is
about 700 MB and unpacks to about 1.7 GB. Xcode uses it for the documentation search behind its
coding-intelligence features. If it hasn't appeared after a while, open Xcode ▸ Settings ▸
Intelligence, finish setup there, and leave Xcode open on a network connection. Apple doesn't
document a separate download switch. Once the asset is on disk, apple-doc doesn't need Xcode
running, or even installed.

## Install

```bash
uv tool install git+https://github.com/banagale/apple-doc
# or, from a clone
git clone https://github.com/banagale/apple-doc && cd apple-doc && uv tool install .
```

A PyPI release is planned.

## First run

Build the keyword index once:

```console
$ apple-doc --build
indexed 241590 docs from /System/Library/AssetsV2/com_apple_MobileAsset_AppleDeveloperDocumentation/<hash>.asset/AssetData/documentation-db/index.sql in 6s -> ~/Library/Caches/apple-doc/fts.sqlite (120 MB)
```

The build takes a few seconds on Apple silicon. macOS replaces the asset when it updates the
documentation. When that happens, every search prints a one-line reminder on stderr; run
`apple-doc --build` again.

## Usage

```text
usage: apple-doc [options] QUERY...
       apple-doc --full URI | --build | --doctor | --list-frameworks

Search Apple's developer documentation offline: API reference for every framework,
declarations, availability, articles and the Human Interface Guidelines. Reads the copy of
the documentation that macOS downloads for Xcode; no network, no Xcode process.

The search is keyword-based: pass API names and the words Apple's pages use, not sentences.
Results prefer symbols available on macOS (see --any-platform). Put "--" before a query
that starts with "-", e.g. apple-doc -- -initWithFrame.

positional arguments:
  QUERY                 API names and topic words

options:
  -h, --help            show this help message and exit
  --framework NAME, -f NAME
                        restrict to one framework, e.g. AppKit, WebKit, Foundation, SwiftUI,
                        "Human Interface Guidelines" (case-insensitive; see --list-frameworks)
  --limit N, -n N       number of hits to show (default 3)
  --lines N             matching body lines per hit, shown after its summary and declaration
                        (default 4)
  --any-platform        do not prefer macOS-available symbols
  --max-lines N         cap on total output lines for a text search (default 60)
  --full URI            print one whole page or section (first 80 lines); URI is the path
                        (/documentation/... or /design/...) or developer.apple.com URL shown under
                        a hit
  --json                JSON output for a search, --full (whole page) or --list-frameworks
  --build               (re)build the keyword index; run once, and after macOS/Xcode updates
                        replace the documentation
  --doctor              check the documentation asset and the index, then exit
  --list-frameworks     list the framework names --framework accepts, with page counts
  --version, -V         show program's version number and exit

examples:
  apple-doc --build                                  build the index (once, and after updates)
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

environment:
  APPLE_DOC_INDEX       index file (default ~/Library/Caches/apple-doc/fts.sqlite)
  APPLE_DOC_ASSET_GLOB  glob for Apple's documentation-db/index.sql
```

### Examples

```bash
apple-doc NSTextView undo -f AppKit                 # class + member, one framework
apple-doc NSWindow becomeKey notification -n 5      # more hits
apple-doc toolbars -f "Human Interface Guidelines"
apple-doc --list-frameworks                         # names -f accepts, with page counts
apple-doc --full '/documentation/AppKit/NSResponder/noResponder(for:)'
apple-doc --full https://developer.apple.com/documentation/appkit/nsview   # URLs work, any case
apple-doc --full supporting-dark-mode-in-your-interface   # a unique last segment works too
apple-doc --json SecItemAdd -f Security | jq -r '.hits[] | "\(.title)\t\(.url)"'
```

Quote `--full` paths. Swift selectors contain parentheses, and zsh treats unquoted
parentheses as a glob. `--full` also accepts `http://` URLs, `?language=` suffixes and a
missing leading slash. If the exact path isn't found, it looks for a single page whose last
segment matches, and lists the candidates when there are several.

JSON output:

- A search prints `{query, terms, candidates, seconds, stale_index, hits: [{rank, title,
  framework, role, availability, uri, url, excerpt, score}]}`. A search with no hits still
  prints this object, with `hits: []` and exit code 1. `--max-lines` doesn't apply.
- `--full` prints `{uri, title, framework, lines}` with every line of the page, not just the
  first 80.
- `--list-frameworks` prints `[{framework, pages}]`.
- Errors are never JSON. They go to stderr as one `apple-doc: ...` line, so check the exit code
  before parsing stdout.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success (a search with at least one hit, a page printed, index built, doctor all clear) |
| 1 | The search ran and found nothing |
| 2 | Usage error: unknown flag, missing or empty query, unknown `--framework` (with suggestions), conflicting modes |
| 3 | Apple's documentation asset not found, or not a readable documentation database |
| 4 | Index missing or unreadable; `--doctor` also returns 4 when the index is stale |
| 5 | `--full`: no page at that path |

A stale index doesn't fail a search. The search still runs, and one line on stderr tells you to
rebuild. When text output hits the `--max-lines` cap, the last line says so.

## Forming queries (for humans and AI agents)

**Pass entities, not sentences.** The search matches words, not meaning. You, or your agent,
are the semantic layer. Before searching, translate the question into the class, method,
notification and topic names Apple's pages use.

This approach comes from [Contextify](https://contextify.sh)'s
[Total Recall](https://contextify.sh/total-recall/) skill. There, the agent searches its own
past AI coding sessions by turning a question into the concrete names and terms the record
uses, then runs a few small queries. The agent supplies the meaning, and the index stays a
fast, local keyword index. apple-doc applies the same split to Apple's documentation.

| Question | Query |
|---|---|
| "store a password securely" | `Keychain SecItemAdd generic password` (the sentence finds Password AutoFill instead) |
| "why does my text view stay dirty after undo" | `NSTextView undo textDidChange -f AppKit`, then `NSUndoManager didUndoChangeNotification` |
| "images in my HTML don't load" | `WKWebView loadHTMLString baseURL relative -f WebKit` |
| "colours are wrong in dark mode" | `dark mode appearance -f AppKit` (articles), then `performAsCurrentDrawingAppearance` |
| "what does Apple say about toolbars" | `toolbars -f "Human Interface Guidelines"` |

- **Run 2 or 3 small queries, not one.** Try the class plus the member, then the notification or
  delegate method, then the topic word. Different wording finds different pages.
- **Don't know the API name? Start from the topic article.** Apple's overview articles are titled
  by topic ("Appearance Customization", "Drag and Drop", "Keychain services"). Query the topic
  words with `-n 5` and open the article with `--full`. Then query the symbol names it mentions;
  they print as `` `name` ``. Links to other articles print as paths you can pass straight to
  `--full`.
- **Narrow with `-f FRAMEWORK`**: AppKit, WebKit, SwiftUI, Foundation, Security, and so on.
  `--list-frameworks` shows every name. Results prefer macOS symbols. Use `--any-platform` for
  iOS-only APIs.
- **Articles that cover several platforms are often filed under UIKit or SwiftUI**, even when
  they cover macOS too. For example, "Supporting Dark Mode in your interface" lives under UIKit.
  Drop `-f` when you are looking for an article.
- **Read the excerpt, then `--full` the one page you need.**
- **Absence needs 2 or 3 different queries** before you conclude a page doesn't exist.
- **The docs don't cover everything.** Some behaviour Apple never documents, for example
  whether undo posts `textDidChange`. That needs a small test program, not a guess.

## Using it from AI coding agents

Any agent with a shell can run `apple-doc` once it's on `PATH`. The default output is sized for
a context window: 3 hits and at most 60 lines. Exit codes let a script branch without parsing
text.

A ready-made skill file is in [`skills/apple-doc/SKILL.md`](skills/apple-doc/SKILL.md). It
contains the usage summary and the query guidance above, written for an agent. Install it where
your agent looks for skills:

```bash
# Claude Code
mkdir -p ~/.claude/skills/apple-doc
curl -fsSL https://raw.githubusercontent.com/banagale/apple-doc/main/skills/apple-doc/SKILL.md \
  -o ~/.claude/skills/apple-doc/SKILL.md

# Codex
mkdir -p ~/.agents/skills/apple-doc
curl -fsSL https://raw.githubusercontent.com/banagale/apple-doc/main/skills/apple-doc/SKILL.md \
  -o ~/.agents/skills/apple-doc/SKILL.md
```

Or paste a short rule into `AGENTS.md` / `CLAUDE.md`:

```markdown
Before relying on how an Apple API behaves, check it with `apple-doc` (offline Apple docs):
`apple-doc ClassName memberName -f Framework`. Pass API names, not sentences; run 2-3 queries;
open one page with `apple-doc --full '<uri>'`.
```

## How it works

- **Apple's database.** `documentation-db/index.sql` in the asset has a `documents` table: one
  row per page or section, keyed by its documentation path (for example
  `/documentation/AppKit/NSTextView#Supporting-undo`). Each row is JSON with title, role,
  framework, type, platform availability and the full page as Markdown. Apple's own index is a
  vector index built with a private embedding model, and its keyword search is turned off.
- **apple-doc's index.** `--build` reads every row once. It writes a contentless SQLite FTS5
  index (porter stemming) to `~/Library/Caches/apple-doc/fts.sqlite`, about 120 MB. The index
  holds three weighted columns: title; identifiers (path segments and declaration names, split on
  camelCase and also joined, so `noResponderFor` finds `noResponder(for:)`); and body text. It
  also keeps a small metadata table (path, framework, type, macOS availability) and the asset
  path and mtime it was built from. It stores no page text. Link-list sections such as
  "Relationships" and "See Also" are skipped.
- **Search.** The query's words and their camelCase parts become an FTS5 `OR` query. The top 400
  candidates by BM25 are re-ranked using the page text read back from Apple's database. The
  re-ranking favours pages that cover more of your words and pages whose name matches a word. It
  puts the page itself before its sections, prefers macOS-available symbols, and slightly demotes
  topic list pages. Excerpts come straight from Apple's text, so they always match the source.
- **Read-only, local only.** Apple's database is opened with SQLite's `mode=ro&immutable=1`.
  apple-doc has no network code and needs no sudo. The only file it writes is its own index.
  Delete `~/Library/Caches/apple-doc/` to undo.

## Limitations

- **Keyword search, not semantic search.** A plain-English question ranks worse than in Xcode's
  semantic search. Name the API, or search the topic first; see "Forming queries".
- **A private, undocumented format.** The asset's location and schema are not a public Apple
  API. A macOS or Xcode update can move or change them. `apple-doc --doctor` shows what it finds,
  and an issue report with that output helps.
- **Apple's docs, Apple's gaps.** Behaviour Apple doesn't document isn't in the corpus.
- **Versions come from Apple's data as numbers,** so macOS 10.10 shows as `10.1`.
- **macOS only.** The documentation asset exists only on macOS.

## Prior art

Other tools that do related jobs; pick the one that fits:

- [XCDocs](https://github.com/BitrigApp/XCDocs) (Swift, MIT) runs real semantic search over the
  same asset. It loads Apple's private embedding and vector-search frameworks, so plain-English
  questions work better than here. It returns whole pages rather than ranked excerpts, and has no
  platform preference.
- [Ahmetshbzz/apple-docs-mcp](https://github.com/Ahmetshbzz/apple-docs-mcp) (Python, MIT) is an
  MCP server and CLI with a similar FTS5 index over the asset. It can also route questions to
  Xcode's own search through `mcpbridge`.
- [akkyie/xcdoc](https://github.com/akkyie/xcdoc) (Swift, MIT) renders full articles from
  Xcode's documentation cache. It ships a Claude Code hook that redirects developer.apple.com
  fetches to the local copy.
- [sosumi.ai](https://github.com/NSHipster/sosumi.ai) (NSHipster, MIT) fetches developer.apple.com
  live and converts pages to Markdown for LLMs, over MCP or `npx`. It works on any OS but needs
  the network.
- [kimsungwhee/apple-docs-mcp](https://github.com/kimsungwhee/apple-docs-mcp) and
  [MightyDillah/apple-doc-mcp](https://github.com/MightyDillah/apple-doc-mcp) are MCP servers
  over the online documentation.
- Xcode's own `DocumentationSearch` tool, through `xcrun mcpbridge`, is the semantic original.
  It needs Xcode, and it isn't offered to headless agents.

apple-doc's niche: a plain offline command with no dependencies, small ranked excerpts that fit
an agent's context, macOS-first ranking, and exit codes for scripting.

## Not affiliated with Apple

apple-doc is an independent project. It is not affiliated with, endorsed by or supported by
Apple Inc. It ships no Apple content. It reads the copy of the documentation that your own Mac
downloaded, and stores only a keyword index of it on your machine. Apple, Xcode, macOS and
related names are trademarks of Apple Inc.

## Development

```bash
git clone https://github.com/banagale/apple-doc && cd apple-doc
uv sync
uv run pytest            # tests build a tiny fake asset; the real one is optional
uv run ruff check . && uv run ruff format --check .
```

Tests marked `real_asset` run only when Apple's asset is present. Point the tool at another
asset or index with `APPLE_DOC_ASSET_GLOB` and `APPLE_DOC_INDEX`. Issues and pull requests are
welcome.

## About

Built by the team behind [Contextify](https://contextify.sh), we build tools that give AI agents context; this one gives them Apple's documentation.

## License

[MIT](LICENSE)
