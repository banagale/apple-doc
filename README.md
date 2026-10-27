# apple-doc

An AI-agent-first CLI and skill for Apple's developer documentation, using the offline copy
Xcode keeps on your Mac.

Coding agents guess how Apple APIs behave: they invent members, assume the wrong macOS version
and miss the one sentence that explains the bug. apple-doc lets the agent look it up instead,
offline, in an answer sized for its context: the declaration, the availability and the lines that
matter.

```text
> /apple-doc Why do my layer colours stay light in Dark Mode?
```

```console
$ apple-doc updateLayer performAsCurrentDrawingAppearance -f AppKit -n 2 --lines 2
1. performAsCurrentDrawingAppearance(_:)  [AppKit, Instance Method, macOS 11+]
   Instance Method of NSAppearance
   Sets the appearance to be the active drawing appearance and perform the specified block.
     func performAsCurrentDrawingAppearance(_ block: () -> Void)
   The block to invoke after setting the appearance to be the current drawing appearance.
   This method saves and restores the previous current appearance.
   https://developer.apple.com/documentation/AppKit/NSAppearance/performAsCurrentDrawingAppearance(_:)

2. updateLayer()  [AppKit, Instance Method, macOS 10.8+]
   Instance Method of NSView
   Updates the view’s content by modifying its underlying layer.
     func updateLayer()
   You use this method to optimize the rendering of your view in situations where you can represent your views contents entirely using a layer object. If your view’s `wantsUpdateLayer` property is `true`, the view calls thi...
   When you want to update the contents of your layer, mark the view as dirty by setting its `needsDisplay` property to `true`. Doing so adds the view to the list of views that need to be refreshed during the next update cy...
   https://developer.apple.com/documentation/AppKit/NSView/updateLayer()

(400 candidates, 0.17s; full page: apple-doc --full URI)
```

No network, no API key, no Xcode running; about 0.05 s per query. Also runs as an MCP server
(`apple-doc --mcp`) for clients that only take MCP, and of course supports json output.

## Install

```bash
uv tool install git+https://github.com/banagale/apple-doc@v0.1.0   # Python 3.11+, no dependencies
apple-doc --build                                                  # one-time keyword index, a few seconds
```

Needs a Mac with Apple's documentation on disk. Xcode downloads it; tested on macOS 27 with
Xcode 27. `apple-doc --doctor` checks the setup.

<details>
<summary>Troubleshooting</summary>
<ul>
<li><strong><code>apple-doc: command not found</code></strong>: uv's tool folder isn't on your PATH. Run
<code>uv tool update-shell</code> and open a new shell. Agents need it on their PATH too.</li>
<li><strong>Exit 3, documentation missing</strong>: see <a href="#getting-the-documentation">Getting the documentation</a>.</li>
<li><strong>Exit 4, index missing</strong>: run <code>apple-doc --build</code>. Searches print a one-line reminder when
macOS updates the documentation.</li>
</ul>
</details>

## Connect your agent

**Claude Code or Codex: install the skill.** It tells the agent when to reach for `apple-doc`
and how to turn a question into a query.

```bash
apple-doc --install-skill        # ~/.claude/skills and/or ~/.agents/skills, whichever exist
```

Restart the agent, then ask it about an Apple API, or call the skill directly with
`/apple-doc <question>`. Use `--agent claude|codex|all` to choose, or `--dir SKILLS_DIR` for
another agent's skills folder (it writes `SKILLS_DIR/apple-doc/SKILL.md`). It never overwrites a
different `SKILL.md` without `--force`.

**Clients that only take MCP: run `apple-doc --mcp`**, a stdio server with three tools,
`search_apple_docs`, `read_apple_doc` and `list_frameworks`.

```bash
claude mcp add --scope user apple-doc -- apple-doc --mcp     # Claude Code
codex mcp add apple-doc -- apple-doc --mcp                   # Codex
```

<details>
<summary>Cursor, VS Code, Claude Desktop, Devin Desktop, Windsurf and other MCP clients</summary>
<p>Most clients take this block: <code>~/.cursor/mcp.json</code>, Claude Desktop's
<code>~/Library/Application Support/Claude/claude_desktop_config.json</code>, Devin Desktop's
<code>~/.config/devin/mcp_config.json</code> (for its Cascade agent, per
<a href="https://docs.devin.ai/desktop/cascade/mcp">Devin's docs</a>), and legacy Windsurf's
<code>~/.codeium/windsurf/mcp_config.json</code>.</p>
<pre lang="json"><code>{
  "mcpServers": {
    "apple-doc": { "command": "apple-doc", "args": ["--mcp"] }
  }
}
</code></pre>
<p>VS Code (<code>.vscode/mcp.json</code>) uses <code>"servers"</code> and wants <code>"type": "stdio"</code>:</p>
<pre lang="json"><code>{
  "servers": {
    "apple-doc": { "type": "stdio", "command": "apple-doc", "args": ["--mcp"] }
  }
}
</code></pre>
<p>GUI apps often don't see your shell's PATH. If the server doesn't start, use the full path that
<code>command -v apple-doc</code> prints. If a client runs the server with a different <code>HOME</code> and reports
"no index yet", point it at your index with an <code>env</code> entry:
<code>"env": { "APPLE_DOC_INDEX": "/Users/YOU/Library/Caches/apple-doc/fts.sqlite" }</code>. The server
never builds the index itself; run <code>apple-doc --build</code> in a terminal first.</p>
</details>

**Anything else** (Cursor rules, `AGENTS.md`, a local model's system prompt): paste the output
of `apple-doc --print-skill`, or this:

```markdown
Before relying on how an Apple API behaves, check it with `apple-doc` (offline Apple docs).
Pass API names, not sentences: `apple-doc ClassName memberName -f Framework`. Run 2-3 small
queries, then open one page with `apple-doc --full '<path>'`. Exit 1 means no hits: rephrase.
```

**Skill or MCP?** Prefer the skill when the agent has a shell: nothing sits in its context until a
query runs, and the agent learns how to search. Use MCP for clients without a shell or skills.

## Examples

You ask the agent a question; it turns it into API names and runs a few small lookups:

```bash
# "Does NSTextView post textDidChange on undo?"
apple-doc NSTextView undo textDidChange -f AppKit
apple-doc NSUndoManager didUndoChangeNotification

# "Store a password securely"
apple-doc Keychain SecItemAdd generic password

# "Relative image paths don't load in my WKWebView"
apple-doc loadHTMLString baseURL relative -f WebKit

# "What does the HIG say about toolbars?"
apple-doc toolbars -f "Human Interface Guidelines"

# Read the one page that matters (quote it: zsh globs the parentheses)
apple-doc --full '/documentation/WebKit/WKWebView/loadHTMLString(_:baseURL:)'

# Script it
apple-doc --json NSWindow becomeKey | jq '.hits[].uri'
```

## How the agent searches

The index matches words; the meaning comes from the agent. The skill teaches it to turn a question
into the class, member, notification and topic names Apple's pages use, run 2 or 3 small queries,
and open the one page that answers it with `--full`. If it doesn't know the API, it searches the
topic, reads the overview article, then queries the symbols that article names. This split
between an agent that understands and a fast keyword index comes from
[Contextify](https://contextify.sh)'s [Total Recall](https://contextify.sh/total-recall/) skill.

## Reference

Output is bounded: 3 hits by default and at most 60 lines for a text search. `--full` prints one
page or section, up to 80 lines of content followed by its availability and section anchors.
`--json` returns the same search results as structured data, and the whole page for `--full`.
Run `apple-doc --help` for every flag. Errors are one line on stderr.

| Exit | Meaning | Exit | Meaning |
| ---- | ------- | ---- | ------- |
| 0 | success (still check hits answer the question) | 4 | index missing or unreadable: run `--build`; also a stale index under `--doctor` |
| 1 | no hits: rephrase | 5 | `--full` page not found (suggests paths) |
| 2 | usage error (an unknown `-f` lists suggestions) | 6 | `--install-skill` left a file alone |
| 3 | documentation asset missing or unreadable | | |

## Getting the documentation

`apple-doc --doctor` checks for it. If it's missing, install Xcode and open it: macOS downloads
the documentation in the background (about 700 MB). If it doesn't appear, open Xcode ▸ Settings ▸
Intelligence and leave Xcode open on a network connection. After that, apple-doc doesn't need
Xcode running.

## How it works

Recent Xcode releases keep about 263,000 documentation pages as a SQLite database under
`/System/Library/AssetsV2/`. `--build` writes a keyword index of it (about 120 MB, no page text)
to `~/Library/Caches/apple-doc/`; searches rank against Apple's own text, macOS first. Apple's file
is opened read-only, with no network and no sudo. Delete the cache folder to undo.

## Limitations

Availability is Apple's data as stored in the asset. A few macOS 10.10 APIs are stored as `10.1`
(WKWebView's `loadHTMLString(_:baseURL:)`, for one), so verify a version that looks wrong, for
example against the SDK headers. apple-doc doesn't reinterpret `10.1`.

## Development

```bash
git clone https://github.com/banagale/apple-doc && cd apple-doc
uv sync && uv run pytest     # tests use a tiny fake asset; the real one is optional
```

Issues and pull requests are welcome.

## Not affiliated with Apple

An independent project, not affiliated with or endorsed by Apple Inc. It doesn't bundle or redistribute Apple's documentation: it reads the copy your own Mac downloaded. The tests quote a few short excerpts as fixtures. Apple, Xcode and macOS are trademarks of Apple Inc.

## About

I also built [Contextify](https://contextify.sh). I enjoy building tools that give AI agents context.

## License

[MIT](LICENSE)
