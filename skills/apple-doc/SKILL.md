---
name: apple-doc
description: "Search Apple's developer documentation offline: API reference (AppKit, WebKit, SwiftUI, Foundation and every other framework), declarations, availability, articles and the Human Interface Guidelines, from the copy macOS keeps on disk for Xcode. Use before relying on how an Apple API behaves (what it posts, when it runs, what a parameter means, which macOS version has it), when checking a HIG rule, or instead of fetching developer.apple.com."
---

# apple-doc: Apple's developer documentation, offline

`apple-doc` searches the documentation database that macOS downloads for Xcode. No network, no
Xcode process; a query takes well under a second. Output is a few ranked hits, each with title,
framework, macOS availability, declaration, the best-matching lines and the page URL, capped at
60 lines.

```bash
apple-doc NSTextView undo -f AppKit          # search; put class and method names in the query
apple-doc loadHTMLString baseURL relative -f WebKit -n 5
apple-doc toolbars -f "Human Interface Guidelines"
apple-doc --full '/documentation/AppKit/NSResponder/noResponder(for:)'   # one whole page; quote it
apple-doc --json NSWindow becomeKey          # same search as JSON
apple-doc --list-frameworks                  # names that -f accepts
```

## Forming queries: you are the semantic layer

The search matches words, not meaning. Translate the question into the names and vocabulary
Apple's pages use before searching:

| Question | Query |
|---|---|
| "store a password securely" | `Keychain SecItemAdd generic password` (the sentence finds Password AutoFill instead) |
| "why does my text view stay dirty after undo" | `NSTextView undo textDidChange -f AppKit`, then `NSUndoManager didUndoChangeNotification` |
| "images in my HTML don't load" | `WKWebView loadHTMLString baseURL relative -f WebKit` |
| "colours are wrong in dark mode" | `dark mode appearance -f AppKit` (articles), then `performAsCurrentDrawingAppearance` |
| "what does Apple say about toolbars" | `toolbars -f "Human Interface Guidelines"` |

- Run 2-3 bounded queries, not one: class plus member, then the notification or delegate method,
  then the topic word.
- Don't know the API? Search the topic words with `-n 5`, open the overview article with `--full`,
  and query the symbol names it mentions (they print as `` `name` ``; article links print as
  paths you can pass to `--full`).
- Narrow with `-f FRAMEWORK`. Results prefer macOS symbols; `--any-platform` turns that off.
  Cross-platform articles are often filed under UIKit or SwiftUI, so drop `-f` to find an article.
- `--full` on a page ends with its section anchors; long articles keep their content in those
  sections, so open the one you need with `--full '<page>#<anchor>'`.
- Absence needs 2-3 materially different queries before you conclude a page doesn't exist.
- Apple doesn't document everything. Undocumented behaviour needs a small probe program, not a guess.

## Exit codes and upkeep

0 ok, 1 no hits, 2 usage (including an unknown `-f` name, with suggestions), 3 documentation
asset missing or unreadable, 4 index missing (run `apple-doc --build`), 5 page not found.
Errors are one line on stderr, also in `--json` mode. A one-line stderr hint says when the index is older than the documentation;
run `apple-doc --build` (seconds). `apple-doc --doctor` checks the setup.
