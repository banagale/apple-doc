"""Runs only on a Mac that has Apple's documentation asset; needs no index."""

import glob
import subprocess
import sys

import pytest

from apple_doc.index import DEFAULT_ASSET_GLOB

pytestmark = pytest.mark.real_asset


@pytest.mark.skipif(not glob.glob(DEFAULT_ASSET_GLOB), reason="Apple documentation asset absent")
def test_full_reads_a_real_page():
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "apple_doc",
            "--full",
            "/documentation/AppKit/NSResponder/noResponder(for:)",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "noResponder" in r.stdout and "beep" in r.stdout
