"""Install the bundled agent skill (SKILL.md) for Claude Code, Codex or any other agent."""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib.resources import files

from apple_doc.errors import USAGE, AppleDocError

SKILL_NAME = "apple-doc"
# agent -> (directory whose existence means "this agent is set up here", skills directory)
AGENTS = {
    "claude": ("~/.claude", "~/.claude/skills"),
    "codex": ("~/.agents", "~/.agents/skills"),
}


def skill_text() -> str:
    """The SKILL.md shipped inside this package, so it always matches the CLI version."""
    return files("apple_doc").joinpath("SKILL.md").read_text(encoding="utf-8")


@dataclass
class Outcome:
    path: str  # the SKILL.md path
    status: str  # wrote | updated | unchanged | refused
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status != "refused"

    def line(self) -> str:
        text = "%-9s %s" % (self.status + ":", self.path)
        return text + ("  (%s)" % self.detail if self.detail else "")


def target_dirs(agent: str | None, directory: str | None) -> list[str]:
    """Skill directories to install into, from --agent / --dir or what exists in $HOME."""
    if directory:
        if agent:
            raise AppleDocError("pass either --agent or --dir, not both", USAGE)
        return [os.path.abspath(os.path.expanduser(directory))]
    if agent in AGENTS:
        names = [agent]
    elif agent == "all":
        names = list(AGENTS)
    else:
        names = [n for n, (home, _) in AGENTS.items() if os.path.isdir(os.path.expanduser(home))]
        if not names:
            raise AppleDocError(
                "found neither ~/.claude nor ~/.agents; pass --agent claude|codex|all, or "
                "--dir PATH for another agent's skills folder (or use --print-skill)",
                USAGE,
            )
    return [os.path.join(os.path.expanduser(AGENTS[n][1]), SKILL_NAME) for n in names]


def _symlink_in_path(path: str, stop: str) -> str | None:
    """The first symlink among path and its parents below ``stop`` (e.g. $HOME), if any."""
    stop = os.path.abspath(stop)
    p = os.path.abspath(path)
    while p not in (stop, os.path.dirname(p)):
        if os.path.islink(p):
            return p
        p = os.path.dirname(p)
    return None


def install(dest_dir: str, force: bool = False) -> Outcome:
    text = skill_text()
    path = os.path.join(dest_dir, "SKILL.md")
    home = os.path.expanduser("~")
    link = _symlink_in_path(path, home if dest_dir.startswith(home) else os.path.dirname(dest_dir))
    if link and not force:
        return Outcome(
            path,
            "refused",
            "%s is a symlink to %s; not writing through it. Update that copy yourself, "
            "or rerun with --force" % (link, os.path.realpath(link)),
        )
    if os.path.isdir(path):
        return Outcome(path, "refused", "SKILL.md is a directory")
    existing = None
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                existing = f.read()
        except (OSError, UnicodeDecodeError):
            existing = ""
    if existing == text:
        return Outcome(path, "unchanged", "already matches this version")
    if existing is not None and not force:
        return Outcome(path, "refused", "a different SKILL.md is there; rerun with --force")
    try:
        os.makedirs(dest_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as e:
        return Outcome(path, "refused", "cannot write: %s" % e)
    return Outcome(path, "updated" if existing is not None else "wrote", "")
