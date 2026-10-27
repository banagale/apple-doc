import json
import os

from apple_doc import __version__
from tests.conftest import INDEXED


def test_builds_an_index_and_finds_api_pages_offline(tool):
    # Ported from the original single-script test.
    assert "no index yet" in tool("beep").stderr
    assert "indexed %d docs" % INDEXED in tool("--build").stdout
    out = tool("noResponderFor", "beep").stdout
    assert out.startswith("1. noResponder(for:)") and "beeps if eventSelector is keyDown" in out
    out = tool("loadHTMLString", "baseURL", "relative", "-f", "WebKit").stdout
    assert "resolves relative URLs" in out and "UIView" not in out
    full = tool("--full", "/documentation/AppKit/NSResponder/noResponder(for:)").stdout
    assert "falls off the end of the responder chain" in full


def test_hit_header_shows_framework_role_and_availability(built):
    out = built("noResponderFor").stdout
    assert out.splitlines()[0] == "1. noResponder(for:)  [AppKit, Instance Method, macOS 10.0+]"
    assert "https://developer.apple.com/documentation/AppKit/NSResponder/noResponder(for:)" in out
    assert "  func noResponder(for eventSelector: Selector)" in out


def test_framework_filter_is_case_insensitive_and_exclusive(built):
    data = built.json("glimmerKey", "-n", "10", "-f", "uikit")
    assert [h["framework"] for h in data["hits"]] == ["UIKit"]
    data = built.json("glimmerKey", "-n", "10", "--framework", "AppKit")
    assert [h["framework"] for h in data["hits"]] == ["AppKit"]


def test_macos_symbols_preferred_unless_any_platform(built):
    # On raw relevance the iOS page edges ahead; the macOS preference flips the order.
    default = built.json("glimmerKey", "sparkle", "-n", "2")
    assert [h["framework"] for h in default["hits"]] == ["AppKit", "UIKit"]
    anyp = built.json("glimmerKey", "sparkle", "-n", "2", "--any-platform")
    assert [h["framework"] for h in anyp["hits"]] == ["UIKit", "AppKit"]


def test_link_list_sections_are_not_indexed(built):
    r = built("zebrafishcontainer")
    assert r.returncode == 1
    assert "no hits for: zebrafishcontainer" in r.stdout


def test_page_ranks_before_its_sections(built):
    data = built.json("NSQuokkaView", "-n", "2")
    uris = [h["uri"] for h in data["hits"]]
    assert uris == [
        "/documentation/AppKit/NSQuokkaView",
        "/documentation/AppKit/NSQuokkaView#Overview",
    ]


def test_full_prints_80_lines_and_counts_the_rest(built):
    r = built("--full", "/documentation/AppKit/LongWidget")
    lines = r.stdout.splitlines()
    assert r.returncode == 0
    assert lines[0] == "# LongWidget" and lines[80] == "... (41 more lines)"
    assert lines[81:] == ["", "availability: macOS 10.0+"]


def test_full_accepts_web_url_and_any_case(built):
    url = "https://developer.apple.com/documentation/appkit/nsresponder/noresponder(for:)"
    r = built("--full", url)
    assert r.returncode == 0 and "beeps" in r.stdout
    page = built.json("--full", url)
    assert page["uri"] == "/documentation/AppKit/NSResponder/noResponder(for:)"
    assert page["framework"] == "AppKit"


def test_full_cleans_markdown_links(tool):
    from tests.conftest import make_asset, page

    make_asset(
        tool.root / "y",
        {
            "/documentation/AppKit/LinkPage": page(
                "LinkPage",
                "AppKit",
                "# LinkPage\nSee [`doThing(_:)`](/documentation/AppKit/LinkPage/doThing(_:)) and "
                "[the guide](https://example.test/guide).",
            )
        },
    )
    env = dict(
        tool.env,
        APPLE_DOC_ASSET_GLOB=str(tool.root / "y/*.asset/AssetData/documentation-db/index.sql"),
    )
    out = tool("--full", "/documentation/AppKit/LinkPage", env=env).stdout
    assert "See `doThing(_:)` and the guide." in out


def test_output_is_capped(built):
    out = built("sprocket", "-n", "40").stdout.splitlines()
    assert len(out) == 60
    out = built("sprocket", "-n", "40", "--max-lines", "7").stdout.splitlines()
    assert len(out) == 7
    out = built("sprocket", "-n", "2", "--lines", "1").stdout
    assert out.count("https://developer.apple.com") == 2


def test_json_search_shape(built):
    data = built.json("noResponderFor", "beep")
    assert data["query"] == "noResponderFor beep"
    assert data["stale_index"] is False
    hit = data["hits"][0]
    assert set(hit) >= {
        "rank",
        "title",
        "framework",
        "role",
        "availability",
        "uri",
        "url",
        "excerpt",
    }
    assert hit["url"].startswith("https://developer.apple.com/documentation/")


def test_version_and_help():
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, "-m", "apple_doc", "--version"], capture_output=True, text=True
    )
    assert r.returncode == 0 and r.stdout.strip() == "apple-doc " + __version__ == "apple-doc 0.1.0"
    r = subprocess.run(
        [sys.executable, "-m", "apple_doc", "--help"], capture_output=True, text=True
    )
    assert r.returncode == 0
    assert "exit codes:" in r.stdout and "APPLE_DOC_INDEX" in r.stdout


# --- exit codes ---------------------------------------------------------------------------


def test_exit_2_usage_errors(built):
    for args in (
        [],
        ["--limit", "0", "x"],
        ["--limit", "abc", "x"],
        ["the", "of", "a"],
        ["--build", "--doctor"],
        ["--full", "/documentation/X", "extra"],
        ["--bogus"],
    ):
        r = built(*args)
        assert r.returncode == 2, (args, r.stdout, r.stderr)
        assert r.stderr.strip(), args


def test_exit_3_asset_not_found(tool):
    env = dict(tool.env, APPLE_DOC_ASSET_GLOB=str(tool.root / "nothing/*/index.sql"))
    for args in (["--build"], ["--full", "/documentation/AppKit/NSView"], ["--doctor"]):
        r = tool(*args, env=env)
        assert r.returncode == 3, args
    assert "documentation asset not found" in tool("--build", env=env).stderr


def test_exit_4_index_missing_or_broken(tool):
    r = tool("beep")
    assert r.returncode == 4 and "apple-doc --build" in r.stderr
    tool.index.parent.mkdir(parents=True)
    tool.index.write_text("not a database")
    r = tool("beep")
    assert r.returncode == 4 and "unreadable" in r.stderr


def test_exit_5_page_not_found(built):
    r = built("--full", "/documentation/AppKit/NoSuchThing")
    assert r.returncode == 5 and "no page /documentation/AppKit/NoSuchThing" in r.stderr


def test_exit_1_no_hits(built):
    r = built("qwxzzy")
    assert r.returncode == 1 and "no hits for: qwxzzy" in r.stdout


# --- staleness and doctor ----------------------------------------------------------------


def test_stale_index_prints_rebuild_hint_but_still_searches(built):
    st = os.stat(built.asset)
    os.utime(built.asset, (st.st_atime, st.st_mtime + 100))
    r = built("noResponderFor")
    assert r.returncode == 0 and r.stdout.startswith("1. noResponder(for:)")
    assert r.stderr.strip().splitlines() == [
        "apple-doc: the documentation asset changed since the index was built; "
        "run `apple-doc --build` to refresh it."
    ]
    assert built.json("noResponderFor")["stale_index"] is True
    assert built("--doctor").returncode == 4
    built("--build")
    r = built("noResponderFor")
    assert r.returncode == 0 and r.stderr == ""


def test_newer_asset_directory_makes_index_stale(built):
    from tests.conftest import make_asset

    newer = built.root / "z.asset"
    make_asset(built.root / "tmpz")
    (built.root / "tmpz" / "x.asset").rename(newer)
    os.utime(newer / "AssetData/documentation-db/index.sql", None)
    st = os.stat(built.asset)
    os.utime(built.asset, (st.st_atime, st.st_mtime - 1000))
    assert "apple-doc --build" in built("noResponderFor").stderr


def test_doctor_reports_ok(built):
    r = built("--doctor")
    assert r.returncode == 0, r.stdout
    assert "asset:   ok" in r.stdout and "index:   ok" in r.stdout


def test_doctor_without_index(tool):
    r = tool("--doctor")
    assert r.returncode == 4 and "index:   MISSING" in r.stdout


def test_build_replaces_existing_index(built):
    first = json.loads(built("--json", "noResponderFor").stdout)
    assert "indexed %d docs" % INDEXED in built("--build").stdout
    assert json.loads(built("--json", "noResponderFor").stdout)["hits"] == first["hits"]


# --- release QA fixes ----------------------------------------------------------------------


def test_article_references_print_as_openable_paths(built):
    out = built("glow", "customization", "-f", "AppKit").stdout
    assert "`/documentation/UIKit/glowing-in-the-dark`" in out
    full = built("--full", "/documentation/AppKit/glow-customization#Glow").stdout
    assert "`/documentation/UIKit/glowing-in-the-dark`" in full
    assert "See `NSQuokkaView`." in full  # symbol references stay short


def test_full_resolves_a_unique_last_segment(built):
    for given in ("glowing-in-the-dark", "/documentation/AppKit/glowing-in-the-dark"):
        r = built("--full", given)
        assert r.returncode == 0 and r.stdout.startswith("# Glowing in the dark"), given


def test_full_lists_candidates_when_last_segment_is_ambiguous(built):
    r = built("--full", "init")
    assert r.returncode == 5
    assert "2 pages end that way" in r.stderr
    assert "/documentation/AppKit/NSQuokkaView/init" in r.stderr


def test_full_normalizes_urls(built):
    for given in (
        "http://developer.apple.com/documentation/AppKit/NSQuokkaView?language=objc",
        "documentation/AppKit/NSQuokkaView/",
        "https://developer.apple.com/documentation/appkit/nsquokkaview#overview",
    ):
        r = built("--full", given)
        assert r.returncode == 0 and "NSQuokkaView" in r.stdout, given


def test_full_does_not_cut_long_lines_but_excerpts_do(built):
    full = built("--full", "/documentation/UIKit/glowing-in-the-dark").stdout
    assert max(len(ln) for ln in full.splitlines()) > 300 and "..." not in full
    out = built("glowing", "glow", "paragraph", "--any-platform").stdout
    assert any(ln.endswith("...") and len(ln) <= 230 for ln in out.splitlines())


def test_capped_output_says_so(built):
    out = built("sprocket", "-n", "40", "--max-lines", "7").stdout.splitlines()
    assert len(out) == 7 and out[-1].startswith("... (output capped at 7 lines")


def test_unknown_framework_is_a_usage_error_with_hints(built):
    r = built("glimmerKey", "-f", "App")
    assert r.returncode == 2 and "unknown framework 'App'" in r.stderr and "AppKit" in r.stderr
    r = built("glimmerKey", "-f", "")
    assert r.returncode == 2 and "needs a name" in r.stderr


def test_list_frameworks(built):
    r = built("--list-frameworks")
    assert r.returncode == 0
    names = [ln.split(None, 1)[1] for ln in r.stdout.splitlines()]
    assert names == ["AppKit", "Foundation", "UIKit", "WebKit"]
    data = built.json("--list-frameworks")
    assert {"framework": "Foundation", "pages": 40} in data


def test_junk_asset_fails_cleanly(tool):
    junk = tool.root / "j.asset/AssetData/documentation-db/index.sql"
    junk.parent.mkdir(parents=True)
    junk.write_text("not a database")
    env = dict(tool.env, APPLE_DOC_ASSET_GLOB=str(junk))
    for args in (["--build"], ["--full", "/documentation/AppKit/NSView"], ["--doctor"]):
        r = tool(*args, env=env)
        assert r.returncode == 3, (args, r.stderr)
        assert "Traceback" not in r.stderr
    assert "unreadable" in tool("--build", env=env).stderr
    assert not os.path.exists(str(tool.index) + ".tmp")
    assert "asset:   UNREADABLE" in tool("--doctor", env=env).stdout


def test_index_path_that_is_a_directory(tool):
    tool.index.mkdir(parents=True)
    r = tool("beep")
    assert r.returncode == 4 and "is a directory" in r.stderr


def test_misc_flag_hygiene(built):
    assert built("-V").stdout.strip() == "apple-doc 0.1.0"
    assert built("--lim", "2", "x").returncode == 2  # no prefix abbreviations
    assert built("--json", "--doctor").returncode == 2
    r = built("--full", "")
    assert r.returncode == 2 and "--full needs a path" in r.stderr
    r = built("日本語")
    assert r.returncode == 2 and "non-ASCII" in r.stderr
    r = built("--", "-glimmerKey")
    assert r.returncode == 0 and "glimmerKey()" in r.stdout


def test_full_lists_sections_and_suggests_anchors(built):
    out = built("--full", "/documentation/AppKit/NSQuokkaView").stdout.splitlines()
    i = out.index(
        "1 section, each its own page: apple-doc --full '/documentation/AppKit/NSQuokkaView#ANCHOR'"
    )
    assert out[i + 1 :] == ["  #Overview"]  # link-list sections are not offered
    assert "availability: macOS 10.0+" in out
    data = built.json("--full", "/documentation/AppKit/NSQuokkaView")
    assert data["sections"] == ["Overview"] and data["availability"] == "macOS 10.0+"
    r = built("--full", "/documentation/AppKit/NSQuokkaView#Nope")
    assert r.returncode == 5 and "its sections: #Overview" in r.stderr
