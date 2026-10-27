---
name: apple-doc
description: "Look up Apple's developer documentation offline: API reference for AppKit, UIKit, SwiftUI, WebKit, Foundation and every other framework, declarations, availability, articles and the Human Interface Guidelines. Use before writing or changing code that depends on how an Apple API behaves (what it posts, when it runs, what a parameter means, which OS version has it, whether a member exists), when checking a HIG rule, or instead of fetching developer.apple.com."
---

# apple-doc: check Apple's docs before you rely on an API

Don't guess how an Apple API behaves, and don't invent members. Run `apple-doc` first. It searches
the copy of Apple's documentation that macOS keeps on disk: no network, about 0.05 s per query,
and the output is capped at 60 lines by default so it fits in your context. Each hit gives the title,
framework, macOS availability, the declaration, the lines that best match, and the page path.

```bash
apple-doc NSTextView undo textDidChange -f AppKit      # class + member + the behaviour you care about
apple-doc loadHTMLString baseURL relative -f WebKit -n 5
apple-doc toolbars -f "Human Interface Guidelines"
apple-doc --full '/documentation/AppKit/NSResponder/noResponder(for:)'   # one page; quote the path
```

## Turn the question into entities first

The search matches words, not meaning. You are the semantic layer: before searching, translate
the question into the class, method, notification and topic names Apple's pages use.

| Question | Query |
|---|---|
| "store a password securely" | `Keychain SecItemAdd generic password` (the sentence finds Password AutoFill instead) |
| "why does my text view stay dirty after undo" | `NSTextView undo textDidChange -f AppKit`, then `NSUndoManager didUndoChangeNotification` |
| "images in my HTML don't load" | `WKWebView loadHTMLString baseURL relative -f WebKit` |
| "colours are wrong in dark mode" | `dark mode appearance` (finds the article), then `updateLayer performAsCurrentDrawingAppearance -f AppKit` |
| "what does Apple say about toolbars" | `toolbars -f "Human Interface Guidelines"` |

- Run 2-3 small queries, not one: class plus member, then the notification or delegate method,
  then the topic word.
- Don't know the API? Search the topic words with `-n 5` and open the overview article with
  `--full`. Query the symbol names it mentions (they print as `` `name` ``). Links to other
  articles print as paths you can pass straight to `--full`.
- `--full` on a page ends with its availability and its section anchors. Long articles keep their
  content in those sections, so open the one you need with `--full '<page>#<anchor>'`.
- Narrow with `-f FRAMEWORK` (`apple-doc --list-frameworks` shows the names). Results prefer
  macOS symbols; add `--any-platform` for iOS-only APIs. Cross-platform articles are often filed
  under UIKit or SwiftUI, so drop `-f` when you look for an article.
- Absence needs 2-3 materially different queries before you conclude a page doesn't exist.
- Apple doesn't document everything. For undocumented behaviour, say so and suggest a small probe
  program; don't present a guess as documented.
- Availability is Apple's data as stored. A few macOS 10.10 APIs are stored as `10.1`, so check a
  version that looks wrong (for example against the SDK headers) before relying on it.

## Scripting, exit codes, upkeep

- `--json` gives `{hits: [{title, framework, availability, uri, url, excerpt, ...}]}` for a
  search, and `{lines, availability, sections}` for `--full`. Search, lookup and usage errors are
  one `apple-doc: ...` line on stderr.
- Exit codes: 0 success (hits: check they answer the question), 1 no hits (rephrase), 2 usage
  (an unknown `-f` lists suggestions), 3 documentation asset missing or unreadable, 4 index
  missing or unreadable (run `apple-doc --build`), 5 page not found (the message suggests paths
  or sections).
- A stderr line saying the documentation changed means: run `apple-doc --build` (seconds).
  `apple-doc --doctor` checks the setup. If the command isn't found, the CLI isn't installed or
  not on PATH: `uv tool install git+https://github.com/banagale/apple-doc`, then
  `uv tool update-shell`.
