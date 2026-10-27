"""Turn Apple's page markdown into short, terminal-friendly text."""

from __future__ import annotations

import re

WEB = "https://developer.apple.com"


def _swift_name(m: re.Match) -> str:
    seg = m.group(2).split("#")[0].rstrip("/").rsplit("/", 1)[-1]
    seg = re.sub(r"-[0-9a-z]{4,6}$", "", seg)
    return "`%s`" % (seg if m.group(1).lstrip().startswith(("-", "+")) else m.group(1))


# An article slug ("supporting-dark-mode-in-your-interface") as opposed to a symbol name.
_ARTICLE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$")


def _doc_ref(m: re.Match) -> str:
    """`Name` for a symbol reference, the openable path for an article reference."""
    path, name = m.group(1), m.group(2)
    return "`%s`" % (path if _ARTICLE.match(name) else name)


def clean(line: str, cap: int | None = 220) -> str:
    """Strip markdown links down to their symbol names; cap the line at ``cap`` chars."""
    line = re.sub(r"\[`([^`]+)`\]\((/documentation/\S+?)\)(?=$|\s|[,.;:])", _swift_name, line)
    line = re.sub(r"\[`([^`]+)`\]\([^)]*\)", r"`\1`", line)
    line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)
    line = re.sub(r"<doc://[^/>]*((?:/[^/>]+)*/([^/>]+))>", _doc_ref, line)
    line = re.sub(r"``doc://[^/`]*((?:/[^/`]+)*/([^/`]+))``", _doc_ref, line)
    line = re.sub(r"\s{2,}", " ", line.strip())
    if cap is None or len(line) <= cap:
        return line
    return line[:cap] + "..."


def avail(doc: dict) -> str:
    """macOS availability if the page has it, else the first few platforms."""
    out: list[str] = []
    for p in doc.get("platforms") or []:
        if p.get("platform") not in ("macOS", "Mac Catalyst") and out:
            continue
        s = str(p.get("platform", "?"))
        if p.get("introduced") is not None:
            s += " %s+" % p["introduced"]
        if p.get("deprecated"):
            s += " (deprecated)"
        if p.get("beta"):
            s += " (beta)"
        out.append(s)
    mac = [o for o in out if o.startswith("macOS")]
    return ", ".join(mac or out[:3])


def excerpt(content: str, terms: list[str], maxlines: int) -> list[str]:
    """Role line and abstract, the declaration, then the body lines that best match."""
    lines = content.split("\n")
    head: list[str] = []
    decl: list[str] = []
    # first lines: title, role line, abstract
    i = 0
    while i < len(lines) and len(head) < 3:
        if lines[i].strip() and not lines[i].startswith("```"):
            head.append(clean(lines[i]))
        if lines[i].startswith("```"):
            break
        i += 1
    m = re.search(r"```[a-z]*\n(.*?)```", content, re.S)
    if m:
        decl = [ln.strip() for ln in m.group(1).strip().split("\n") if ln.strip()][:2]
    stems = [t[: max(4, len(t) - 2)] for t in terms]
    scored = []
    for j, ln in enumerate(lines[i:], i):
        cl = clean(ln)
        if not cl or cl.startswith("```") or cl.startswith("|--") or cl in decl:
            continue
        low = cl.lower()
        hits = sum(1 for s in set(stems) if s in low)
        if hits:
            scored.append((hits, -j, cl))
    scored.sort(reverse=True)
    picked = sorted(scored[:maxlines], key=lambda x: -x[1])
    out = head[1:3] + ["  " + d for d in decl]
    for _, _, cl in picked:
        if cl not in out and cl not in head:
            out.append(cl)
    return out[: maxlines + 3]


def page_lines(content: str) -> list[str]:
    """A whole page: prose lines cleaned, code blocks kept verbatim with their indentation."""
    out, in_code = [], False
    for ln in content.split("\n"):
        if ln.startswith("```"):
            in_code = not in_code
            out.append(ln)
        else:
            out.append(ln.rstrip() if in_code else clean(ln, cap=None))
    return out
