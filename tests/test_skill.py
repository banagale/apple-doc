"""--install-skill / --print-skill, always against a temporary HOME."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUNDLED = (ROOT / "src/apple_doc/SKILL.md").read_text()


def test_repo_copy_matches_bundled_skill():
    assert (ROOT / "skills/apple-doc/SKILL.md").read_text() == BUNDLED
    assert BUNDLED.startswith("---\nname: apple-doc\n")


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


def run(home, *args):
    env = {**os.environ, "HOME": str(home)}
    return subprocess.run(
        [sys.executable, "-m", "apple_doc", *args], env=env, capture_output=True, text=True
    )


def claude(home):
    return home / ".claude/skills/apple-doc/SKILL.md"


def codex(home):
    return home / ".agents/skills/apple-doc/SKILL.md"


def test_print_skill(home):
    r = run(home, "--print-skill")
    assert r.returncode == 0 and r.stdout == BUNDLED


def test_default_installs_for_agents_present(home):
    r = run(home, "--install-skill")
    assert r.returncode == 2 and "neither ~/.claude nor ~/.agents" in r.stderr
    (home / ".claude").mkdir()
    r = run(home, "--install-skill")
    assert r.returncode == 0, r.stderr
    assert claude(home).read_text() == BUNDLED and not codex(home).exists()
    assert "wrote:" in r.stdout and str(claude(home)) in r.stdout
    (home / ".agents").mkdir()
    r = run(home, "--install-skill")
    assert r.returncode == 0
    assert "unchanged:" in r.stdout and "wrote:" in r.stdout
    assert codex(home).read_text() == BUNDLED


def test_agent_flag_creates_missing_dirs(home):
    r = run(home, "--install-skill", "--agent", "codex")
    assert r.returncode == 0 and codex(home).read_text() == BUNDLED
    assert not (home / ".claude").exists()
    r = run(home, "--install-skill", "--agent", "all")
    assert r.returncode == 0 and claude(home).exists()


def test_dir_flag(home, tmp_path):
    target = tmp_path / "cursor/skills/apple-doc"
    r = run(home, "--install-skill", "--dir", str(target))
    assert r.returncode == 0 and (target / "SKILL.md").read_text() == BUNDLED
    assert run(home, "--install-skill", "--dir", str(target), "--agent", "claude").returncode == 2


def test_refuses_to_overwrite_a_different_skill_without_force(home):
    claude(home).parent.mkdir(parents=True)
    claude(home).write_text("my own notes")
    r = run(home, "--install-skill", "--agent", "claude")
    assert r.returncode == 6 and "refused:" in r.stdout and "--force" in r.stdout
    assert claude(home).read_text() == "my own notes"
    r = run(home, "--install-skill", "--agent", "claude", "--force")
    assert r.returncode == 0 and "updated:" in r.stdout
    assert claude(home).read_text() == BUNDLED


def test_symlinked_skill_dir_is_left_alone_without_force(home, tmp_path):
    checkout = tmp_path / "someone-elses-repo/apple-doc"
    checkout.mkdir(parents=True)
    (checkout / "SKILL.md").write_text("their version")
    (home / ".agents/skills").mkdir(parents=True)
    (home / ".agents/skills/apple-doc").symlink_to(checkout)
    r = run(home, "--install-skill", "--agent", "codex")
    assert r.returncode == 6 and "is a symlink to" in r.stdout and str(checkout) in r.stdout
    assert (checkout / "SKILL.md").read_text() == "their version"
    r = run(home, "--install-skill", "--agent", "codex", "--force")
    assert r.returncode == 0 and (checkout / "SKILL.md").read_text() == BUNDLED


def test_symlinked_skills_parent_is_detected(home, tmp_path):
    real = tmp_path / "dotfiles/skills"
    real.mkdir(parents=True)
    (home / ".claude").mkdir()
    (home / ".claude/skills").symlink_to(real)
    r = run(home, "--install-skill", "--agent", "claude")
    assert r.returncode == 6 and "symlink" in r.stdout
    assert not (real / "apple-doc").exists()


def test_install_flags_need_install_skill(home):
    for args in (["--force"], ["--agent", "claude"], ["--dir", "/tmp/x"]):
        assert run(home, "x", *args).returncode == 2
    assert run(home, "--install-skill", "--json").returncode == 2
    assert run(home, "--install-skill", "query").returncode == 2
