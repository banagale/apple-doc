from apple_doc.index import camel_parts, ident_text
from apple_doc.render import avail, clean
from apple_doc.search import query_terms


def test_camel_parts():
    assert camel_parts("loadHTMLString") == ["load", "HTML", "String"]
    assert camel_parts("NSTextView") == ["NS", "Text", "View"]


def test_query_terms_drop_stopwords_and_add_camel_parts():
    words, terms = query_terms("how does NSTextView undo")
    assert words == ["NSTextView", "undo"]
    assert terms == ["nstextview", "text", "view", "undo"]


def test_ident_text_joins_selector_names():
    text = ident_text(
        "/documentation/AppKit/NSResponder/noResponder(for:)", "noResponder(for:)", ""
    )
    assert "noResponderfor" in text.split()


def test_clean_reduces_links_to_symbol_names():
    assert clean("[`init()`](/documentation/AppKit/NSView/init()) here") == "`init()` here"
    assert clean("<doc://com.apple.documentation/documentation/AppKit/NSView>") == "`NSView`"
    assert clean("x" * 300).endswith("...")


def test_avail_prefers_macos():
    doc = {
        "platforms": [
            {"platform": "iOS", "introduced": "13.0"},
            {"platform": "macOS", "introduced": "10.15", "deprecated": True},
        ]
    }
    assert avail(doc) == "macOS 10.15+ (deprecated)"
    assert avail({"platforms": [{"platform": "iOS", "introduced": "2.0"}]}) == "iOS 2.0+"
