"""A tiny stand-in for Apple's documentation asset: same table and JSON shape, invented pages."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ASSET_REL = "x.asset/AssetData/documentation-db/index.sql"


def page(title, framework, content, platform="macOS", type_="symbol", role=None):
    doc = {
        "title": title,
        "framework": framework,
        "type": type_,
        "content": content,
        "platforms": [{"platform": platform, "introduced": "10.0"}] if platform else [],
    }
    if role:
        doc["roleHeading"] = role
    return doc


LONG_BODY = "\n".join("Line %d of a long discussion about widgets." % i for i in range(120))

PAGES = {
    "/documentation/AppKit/NSResponder/noResponder(for:)": page(
        "noResponder(for:)",
        "AppKit",
        "# noResponder(for:)\nInstance Method\nHandles the case where an event or action message "
        "falls off the end of the responder chain.\n```\nfunc noResponder(for eventSelector: "
        "Selector)\n```\nThe default implementation beeps if eventSelector is keyDown(with:).",
        role="Instance Method",
    ),
    "/documentation/WebKit/WKWebView/loadHTMLString(_:baseURL:)": page(
        "loadHTMLString(_:baseURL:)",
        "WebKit",
        "# loadHTMLString(_:baseURL:)\nLoads the contents of the specified HTML string.\n```\n"
        "func loadHTMLString(_ string: String, baseURL: URL?) -> WKNavigation?\n```\nThe base URL "
        "to use when the system resolves relative URLs within the HTML string.",
    ),
    "/documentation/UIKit/UIView": page(
        "UIView",
        "UIKit",
        "# UIView\nAn object that manages content for a rectangular area.",
        platform="iOS",
    ),
    # Same symbol on two platforms; the iOS page matches the query more strongly.
    "/documentation/AppKit/FakeWindow/glimmerKey()": page(
        "glimmerKey()",
        "AppKit",
        "# glimmerKey()\nMakes the window glimmer.\n```\nfunc glimmerKey()\n```\nCall glimmerKey."
        " It may also sparkle, depending on the window's configuration and appearance.",
    ),
    "/documentation/UIKit/FakeWindow/glimmerKey()": page(
        "glimmerKey()",
        "UIKit",
        "# glimmerKey()\nMakes the window glimmer.\n```\nfunc glimmerKey()\n```\n"
        "Call glimmerKey to sparkle.",
        platform="iOS",
    ),
    # A page and its sections: the page itself should rank first.
    "/documentation/AppKit/NSQuokkaView": page(
        "NSQuokkaView",
        "AppKit",
        "# NSQuokkaView\nClass\nA view that displays a quokka.\n```\nclass NSQuokkaView\n```",
        role="Class",
    ),
    "/documentation/AppKit/NSQuokkaView#Overview": page(
        "NSQuokkaView",
        "AppKit",
        "## Overview\nNSQuokkaView draws a quokka. Use NSQuokkaView in a window. NSQuokkaView "
        "supports NSQuokkaView animations and NSQuokkaView layers.",
    ),
    # Link-list sections that the index skips.
    "/documentation/AppKit/NSQuokkaView#Relationships": page(
        "NSQuokkaView", "AppKit", "## Relationships\nInherits from zebrafishcontainer."
    ),
    "/documentation/AppKit/NSQuokkaView#See-Also": page(
        "NSQuokkaView", "AppKit", "## See Also\nzebrafishcontainer and friends."
    ),
    "/documentation/AppKit/LongWidget": page("LongWidget", "AppKit", "# LongWidget\n" + LONG_BODY),
    # An article filed under another framework, referenced from an AppKit topic page.
    "/documentation/UIKit/glowing-in-the-dark": page(
        "Glowing in the dark",
        "UIKit",
        "# Glowing in the dark\nMake views glow.\n" + "A very long paragraph about glow. " * 12,
        platform=None,
        type_="article",
    ),
    "/documentation/AppKit/glow-customization#Glow": page(
        "Glow Customization: Glow",
        "AppKit",
        "## Glow\n<doc://com.example.documentation/documentation/UIKit/glowing-in-the-dark>\n"
        "See ``doc://com.example.documentation/documentation/AppKit/NSQuokkaView``.",
        platform=None,
        type_="topic",
    ),
    # Two pages with the same last segment, for the ambiguous --full fallback.
    "/documentation/AppKit/NSQuokkaView/init": page("init", "AppKit", "# init\nAppKit init."),
    "/documentation/UIKit/FakeWindow/init": page("init", "UIKit", "# init\nUIKit init."),
}
# Many near-identical pages, for the output cap.
for i in range(40):
    PAGES["/documentation/Foundation/Sprocket%d" % i] = page(
        "Sprocket%d" % i,
        "Foundation",
        "# Sprocket%d\nA sprocket.\n```\nclass Sprocket%d\n```\nSprocket teeth, sprocket "
        "chains, sprocket gears and more sprocket facts." % (i, i),
    )

INDEXED = len(PAGES) - 2  # the two link-list sections are skipped


def make_asset(root: Path, pages=PAGES) -> Path:
    path = root / ASSET_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE documents(asset_id TEXT, document TEXT)")
    for uri, doc in pages.items():
        db.execute("INSERT INTO documents VALUES(?,?)", (uri, json.dumps(doc)))
    db.commit()
    db.close()
    return path


class Tool:
    def __init__(self, tmp_path: Path):
        self.root = tmp_path
        self.asset = make_asset(tmp_path)
        self.index = tmp_path / "cache" / "fts.sqlite"
        self.env = {
            **os.environ,
            "APPLE_DOC_ASSET_GLOB": str(tmp_path / "*.asset/AssetData/documentation-db/index.sql"),
            "APPLE_DOC_INDEX": str(self.index),
        }

    def __call__(self, *args, env=None):
        return subprocess.run(
            [sys.executable, "-m", "apple_doc", *args],
            env=env or self.env,
            capture_output=True,
            text=True,
        )

    def json(self, *args):
        r = self("--json", *args)
        assert r.returncode in (0, 1), r.stderr
        return json.loads(r.stdout)


@pytest.fixture
def tool(tmp_path):
    return Tool(tmp_path)


@pytest.fixture
def built(tool):
    r = tool("--build")
    assert r.returncode == 0, r.stderr
    return tool
