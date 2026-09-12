"""Test bước 02: trích nội dung HTML, PDF, DOCX."""
import importlib

extract = importlib.import_module("scripts.02_extract")


def headings(md: str) -> list[str]:
    return [line for line in md.split("\n") if line.startswith("#")]


# ---------- HTML ----------

def test_html_keeps_headings_in_order(sample_html):
    title, md = extract.extract_html(sample_html)
    assert title == "Visa holders and migrants"
    assert headings(md) == [
        "# Visa holders and migrants",
        "## Pay and entitlements",
        "## Your visa is protected",
    ]


def test_html_removes_navigation_and_noise(sample_html):
    _, md = extract.extract_html(sample_html)
    for noise in ["Home > Find help", "Share this page", "Copyright", "href"]:
        assert noise not in md


def test_html_list_items_not_duplicated(sample_html):
    _, md = extract.extract_html(sample_html)
    assert md.count("within one working day") == 1, "<p> trong <li> bị lấy hai lần"
    assert "- Cash payments must still meet the minimum wage." in md


def test_html_table_is_kept(sample_html):
    _, md = extract.extract_html(sample_html)
    assert "Student | 48 hours per fortnight" in md


# ---------- PDF ----------

def test_pdf_detects_headings_by_font_size(sample_pdf):
    title, md = extract.extract_pdf(sample_pdf)
    assert title == "Work health and safety in Australia"
    hs = headings(md)
    assert hs[0] == "# Work health and safety in Australia"
    assert "## Getting hurt at work" in hs


def test_pdf_removes_repeated_footer_and_page_numbers(sample_pdf):
    _, md = extract.extract_pdf(sample_pdf)
    assert "Safe Work Australia info sheet" not in md
    assert "\n\n2\n\n" not in md
    assert "protective equipment" in md


# ---------- DOCX ----------

def test_docx_headings_lists_and_tables(sample_docx):
    title, md = extract.extract_docx(sample_docx)
    assert title == "Sexual harassment: know your rights"
    assert headings(md) == ["# Sexual harassment: know your rights", "# What your employer must do"]
    assert "- Make a complaint to the Commission" in md
    assert "Australian Human Rights Commission | 1300 656 419" in md
