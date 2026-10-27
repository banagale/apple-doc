# apple-doc

Apple developer documentation for AI coding agents: an offline lookup that returns the
declaration, the availability and the lines that answer the question, in about 0.05 seconds.

Coding agents guess how Apple APIs behave. They invent members, assume the wrong OS version, and
miss the one sentence in the docs that explains the bug. Fetching developer.apple.com is slow,
needs the network, and a single page can fill a large part of the context window. Yet macOS
already keeps Apple's whole documentation on disk for Xcode. apple-doc lets Claude Code, Codex,
Cursor or a local model query that copy with a plain shell command. Answers stay short and
bounded.

**What your agent does with it.** It turns the question into API names, then runs a few small
lookups:

```bash
# "Does NSTextView post textDidChange on undo?"
apple-doc NSTextView undo textDidChange -f AppKit
# "How do I make relative image paths load in a WKWebView?"
apple-doc loadHTMLString baseURL relative -f WebKit
# "Store a password securely"
apple-doc Keychain SecItemAdd generic password
# "What does the HIG say about toolbars?"
apple-doc toolbars -f "Human Interface Guidelines"
# Read the one page that matters
apple-doc --full '/documentation/WebKit/WKWebView/loadHTMLString(_:baseURL:)'
```

**What it gets back.** The answer to the WKWebView question, from the live tool:

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

## Set up your agent

You need a Mac with Apple's developer documentation on disk. Xcode downloads it; apple-doc is
tested on macOS 27 with Xcode 27. Then:

```bash
uv tool install git+https://github.com/banagale/apple-doc   # the CLI (Python 3.11+, no dependencies)
apple-doc --build           # one-time keyword index of the on-disk docs, a few seconds
apple-doc --install-skill   # skill for Claude Code (~/.claude/skills) and/or Codex (~/.agents/skills)
apple-doc --doctor          # optional check: asset ok, index ok
```

Restart the agent after installing the skill, then ask it something about an Apple API. The
skill tells the agent when to reach for `apple-doc` and how to phrase queries.

- **`apple-doc: command not found`?** uv's tool folder isn't on your PATH yet. Run
  `uv tool update-shell` and open a new shell. Agents need the command on their PATH too.
- **Asset missing (exit 3)?** See [Getting the documentation](#getting-the-documentation).

`--install-skill` installs for whichever of `~/.claude` and `~/.agents` exists. Use
`--agent claude|codex|all` to choose, or `--dir PATH` for another agent's skills folder. It
never overwrites a different `SKILL.md`, and it won't write through a symlinked skill folder,
unless you pass `--force`. The skill ships inside the package, so it always matches the
installed version. Run `apple-doc --print-skill` to see it or pipe it elsewhere.

For an agent without skills (Cursor rules, a local model's system prompt, any `AGENTS.md` or
`CLAUDE.md`), paste the output of `apple-doc --print-skill`, or this short version:

```markdown
Before relying on how an Apple API behaves, check it with `apple-doc` (offline Apple docs).
Pass API names, not sentences: `apple-doc ClassName memberName -f Framework`. Run 2-3 small
queries, then open one page with `apple-doc --full '<path>'`. Exit 1 means no hits: rephrase.
```

## Forming queries: the agent is the semantic layer

**Pass entities, not sentences.** The search matches words, not meaning. The agent (or you)
supplies the meaning by translating the question into the class, method, notification and topic
names Apple's pages use. This keeps the tool small, local and fast, and lets the model do the
part it is good at.

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
| "colours are wrong in dark mode" | `dark mode appearance` (finds the article), then `updateLayer performAsCurrentDrawingAppearance -f AppKit` |
| "what does Apple say about toolbars" | `toolbars -f "Human Interface Guidelines"` |

- **Run 2 or 3 small queries, not one.** Try the class plus the member, then the notification or
  delegate method, then the topic word.
- **Don't know the API name? Start from the topic article.** Query the topic words with `-n 5`
  and open the overview article with `--full`. Then query the symbol names it mentions; they
  print as `` `name` ``. Links to other articles print as paths you can pass to `--full`.
- **Long pages are split into sections.** `--full` on a page ends with its availability and its
  section anchors. Open the section you need with `--full '<page>#<anchor>'`.
- **Narrow with `-f FRAMEWORK`.** `--list-frameworks` shows the names. Results prefer macOS
  symbols; use `--any-platform` for iOS-only APIs. Cross-platform articles are often filed under
  UIKit or SwiftUI, so drop `-f` when looking for an article.
- **Absence needs 2 or 3 different queries** before concluding a page doesn't exist.
- **The docs don't cover everything.** For undocumented behaviour, such as whether undo posts
  `textDidChange`, the agent should say so and suggest a small test program rather than guess.

## Built for agents

- **Bounded output.** 3 hits by default, each with the declaration, availability and best
  matching lines. Total output is capped at 60 lines, and the last line says when the cap was
  hit. `--full` prints one page or section, with long pages split into sections.
- **A plain command, no MCP server.** Any agent that can run a shell command can use it,
  including headless runs, CI jobs and local models. There is nothing to configure or keep
  running.
- **Offline and fast.** No network, no API keys, no Xcode process; about 0.05 s per query.
- **Exit codes an agent can branch on.** 0 success, 1 no hits (rephrase), 2 usage (an unknown `-f`
  lists suggestions), 3 documentation missing, 4 index missing (run `--build`), 5 page not found
  (the message lists candidate paths or sections), 6 `--install-skill` left a file alone. Errors
  are always one line on stderr. Exit 0 means there were hits, not that they are relevant: the
  agent still reads them and rephrases when they miss.
- **`--json`** for scripts and tool wrappers.
  - A search prints `{query, terms, candidates, seconds, stale_index, hits: [{rank, title,
    framework, role, availability, uri, url, excerpt, score}]}`. With no hits it still prints
    this object, with `hits: []` and exit code 1.
  - `--full` prints `{uri, title, framework, lines, availability, sections}` with every line of
    the page.
  - `--list-frameworks` prints `[{framework, pages}]`.
- **macOS-first ranking**, with the page itself ranked before its sections.
- **Self-maintaining.** When macOS updates the documentation, every search prints a one-line
  reminder to run `apple-doc --build`. `apple-doc --doctor` checks the whole setup.

## Command reference

```text
usage: apple-doc [options] QUERY...
       apple-doc --full URI | --build | --doctor | --list-frameworks
       apple-doc --install-skill [--agent claude|codex|all] [--dir PATH] [--force]

Look up Apple's developer documentation offline, in output sized for AI coding agents:
API reference for every framework, declarations, availability, articles and the Human
Interface Guidelines, read from the copy macOS downloads for Xcode. No network, no Xcode
process, no MCP server: any agent with a shell can run it.

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
  --install-skill       install the agent skill (SKILL.md) for Claude Code (~/.claude/skills)
                        and/or Codex (~/.agents/skills); default: whichever of ~/.claude,
                        ~/.agents exists
  --agent {claude,codex,all}
                        with --install-skill: which agent to install for
  --dir PATH            with --install-skill: write SKILL.md into this folder instead (another
                        agent's skills dir)
  --force               with --install-skill: replace a different SKILL.md, or write through a
                        symlink
  --print-skill         print the agent skill (SKILL.md) to stdout
  --version, -V         show program's version number and exit

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
  APPLE_DOC_ASSET_GLOB  glob for Apple's documentation-db/index.sql
```

Quote `--full` paths. Swift selectors contain parentheses, and zsh treats unquoted parentheses
as a glob. `--full` also accepts developer.apple.com URLs (http or https, any case, with
`?language=`), a missing leading slash, or just a page's unique last segment, such as
`apple-doc --full supporting-dark-mode-in-your-interface`.

## Getting the documentation

Check whether Apple's documentation asset is on disk:

```bash
apple-doc --doctor
# or
ls /System/Library/AssetsV2/com_apple_MobileAsset_AppleDeveloperDocumentation/*.asset/AssetData/documentation-db/index.sql
```

If it's missing, install Xcode from the App Store or developer.apple.com and open it. macOS
then downloads the documentation in the background through its asset service. The download is
about 700 MB and unpacks to about 1.7 GB. Xcode uses it for the documentation search behind its
coding-intelligence features. Xcode 26.3 and later are reported to download it; apple-doc is
tested on macOS 27 with Xcode 27. If it hasn't appeared after a while, open Xcode ▸ Settings ▸
Intelligence, finish setup there, and leave Xcode open on a network connection. Apple doesn't
document a separate download switch. Once the asset is on disk, apple-doc doesn't need Xcode
running.

## How it works

Recent Xcode releases keep Apple's documentation, about 263,000 pages and sections, as a SQLite
database under `/System/Library/AssetsV2/`. Xcode's own `DocumentationSearch` tool reads it, but
only inside Xcode; agents outside Xcode aren't offered it. apple-doc reads the same file
directly.

- **Apple's database.** One row per page or section, keyed by its documentation path. Each row
  is JSON with the title, framework, availability and the page as Markdown. Apple's own index is
  a vector index built with a private embedding model.
- **apple-doc's index.** `--build` writes a contentless SQLite FTS5 index to
  `~/Library/Caches/apple-doc/fts.sqlite` (about 120 MB). It has three weighted columns: title;
  identifiers, split on camelCase and also joined, so `noResponderFor` finds
  `noResponder(for:)`; and body text. It also keeps a little metadata and records which asset it
  was built from. It stores no page text, and it skips link-list sections such as "See Also".
- **Search.** The top 400 BM25 candidates are re-ranked against the page text read back from
  Apple's database. The re-ranking rewards coverage of the query and name matches, prefers
  macOS, and puts pages before their sections. Excerpts are Apple's own text.
- **Read-only, local only.** Apple's file is opened read-only and immutable. apple-doc has no
  network code and needs no sudo. Delete `~/Library/Caches/apple-doc/` to undo.

## Limitations

- **Keyword search, not semantic search.** The agent has to name the API or search the topic
  first; see "Forming queries".
- **A private, undocumented format.** The asset's location and schema are not a public Apple
  API, and a macOS or Xcode update can change them. Issue reports with `apple-doc --doctor`
  output help.
- **Apple's docs, Apple's gaps.** Behaviour Apple doesn't document isn't in the corpus.
- **Versions come from Apple's data as numbers,** so macOS 10.10 shows as `10.1`.
- **macOS only.** The documentation asset exists only on macOS.

## Prior art

- [XCDocs](https://github.com/BitrigApp/XCDocs) (Swift, MIT) runs real semantic search over the
  same asset by loading Apple's private embedding and vector-search frameworks. Plain-English
  questions work better there. It returns whole pages rather than ranked excerpts.
- [Ahmetshbzz/apple-docs-mcp](https://github.com/Ahmetshbzz/apple-docs-mcp) (Python, MIT) is an
  MCP server and CLI with a similar FTS5 index over the asset. It can route questions to Xcode's
  own search.
- [akkyie/xcdoc](https://github.com/akkyie/xcdoc) (Swift, MIT) renders full articles from
  Xcode's documentation cache. It ships a Claude Code hook that redirects developer.apple.com
  fetches to the local copy.
- [sosumi.ai](https://github.com/NSHipster/sosumi.ai) (NSHipster, MIT) fetches developer.apple.com
  live and converts pages to Markdown for LLMs. It works on any OS but needs the network.
- [kimsungwhee/apple-docs-mcp](https://github.com/kimsungwhee/apple-docs-mcp) and
  [MightyDillah/apple-doc-mcp](https://github.com/MightyDillah/apple-doc-mcp) are MCP servers
  over the online documentation.
- Xcode's own `DocumentationSearch`, through `xcrun mcpbridge`, needs Xcode and isn't offered to
  headless agents.

apple-doc's niche: a dependency-free offline command with bounded, ranked excerpts sized for an
agent's context, macOS-first ranking, a bundled skill and exit codes to branch on.

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

`src/apple_doc/SKILL.md` is the bundled skill. `skills/apple-doc/SKILL.md` is a copy for
browsing on GitHub, and a test keeps the two identical. Issues and pull requests are welcome.

## About

Built by the team behind [Contextify](https://contextify.sh), we build tools that give AI agents context; this one gives them Apple's documentation.

## License

[MIT](LICENSE)
