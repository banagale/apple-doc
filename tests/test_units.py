from apple_doc.index import camel_parts, ident_text
from apple_doc.render import avail, clean, page_lines
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


def test_page_lines_keep_code_indentation():
    page = "Intro [link](x).\n```swift\nfunc f() {\n    g()  \n}\n```\n  Spaced   prose."
    assert page_lines(page) == [
        "Intro link.",
        "```swift",
        "func f() {",
        "    g()",
        "}",
        "```",
        "Spaced prose.",
    ]


def test_versions_print_as_apple_wrote_them():
    from apple_doc.index import load_doc

    blob = (
        '{"title": "T", "platforms": ['
        '{"platform": "macOS", "introduced": 10.10, "deprecated": false},'
        '{"platform": "iOS", "introduced": 15.0}]}'
    )
    assert avail(load_doc(blob)) == "macOS 10.10+"
    doc = load_doc(blob.replace("10.10", "13.0"))
    assert avail(doc) == "macOS 13.0+"
    assert avail(load_doc(blob.replace("10.10", "13"))) == "macOS 13+"
    ios_only = '{"platforms": [{"platform": "iOS", "introduced": 15.0}]}'
    assert avail(load_doc(ios_only)) == "iOS 15.0+"
    # float artifacts in Apple's data collapse to the intended version
    assert avail(load_doc(blob.replace("10.10", "10.109999999999999"))) == "macOS 10.11+"
    assert avail(load_doc(blob.replace("10.10", "16.399999999999999"))) == "macOS 16.4+"
