"""Bước 02 — Extract: lấy nội dung chính từ HTML/PDF/DOCX, ghi ra Markdown.

Đầu vào : data/raw/<id>.<type> + data/raw/manifest.json
Đầu ra  : data/extracted/<id>.md + data/extracted/manifest.json

Giữ lại heading (#, ##, ###) vì bước 04 cắt chunk theo heading.

Cách chạy:
  python scripts/02_extract.py
  python scripts/02_extract.py --only fwo_visa_holders --force
"""
import argparse
import io
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bs4 import BeautifulSoup, Tag

from config import settings
from lib.io_utils import read_json, write_json
from lib.text_utils import normalize_text

# ====================== HTML ======================

REMOVE_TAGS = ["script", "style", "noscript", "nav", "header", "footer", "aside",
               "form", "button", "svg", "iframe", "template"]
# Phần tử có class/id chứa các từ này thường là menu, breadcrumb, nút chia sẻ...
NOISE_PATTERN = re.compile(
    r"breadcrumb|cookie|share|social|feedback|skip-link|site-nav|sidebar|pagination|print",
    re.I,
)
BLOCK_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table", "dt", "dd", "blockquote"]
CONTAINER_BLOCKS = {"p", "li", "table", "dd", "blockquote"}  # tránh lấy trùng phần tử con


def _is_noise(el: Tag) -> bool:
    if el.name in ("html", "body", "main", "article"):
        return False
    attrs = " ".join(el.get("class", [])) + " " + (el.get("id") or "")
    return bool(NOISE_PATTERN.search(attrs))


def _find_main(soup: BeautifulSoup) -> Tag:
    return (soup.find("main") or soup.find(attrs={"role": "main"}) or soup.find("article")
            or soup.find(id=re.compile(r"main-content|maincontent|content", re.I))
            or soup.body or soup)


def _table_to_md(table: Tag) -> str:
    rows = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def extract_html(data: bytes) -> tuple[str, str]:
    """Trả về (tiêu đề, markdown)."""
    soup = BeautifulSoup(data, "html.parser")
    page_title = soup.title.get_text(strip=True) if soup.title else ""

    for tag in soup.find_all(REMOVE_TAGS):
        tag.decompose()
    for el in soup.find_all(_is_noise):
        el.decompose()

    main = _find_main(soup)
    lines = []
    for el in main.find_all(BLOCK_TAGS):
        # Bỏ phần tử nằm trong một khối đã lấy (ví dụ <p> trong <li>)
        if any(p.name in CONTAINER_BLOCKS for p in el.parents if p is not main):
            continue
        if el.name == "table":
            text = _table_to_md(el)
        else:
            text = el.get_text(" ", strip=True)
        if not text:
            continue
        if el.name[0] == "h" and el.name[1:].isdigit():
            lines.append("#" * int(el.name[1]) + " " + text)
        elif el.name == "li":
            lines.append("- " + text)
        else:
            lines.append(text)

    h1 = main.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else page_title.split("|")[0].strip()
    return title, "\n\n".join(lines)


# ====================== PDF ======================

def extract_pdf(data: bytes) -> tuple[str, str]:
    """PDF không có heading thật: đoán heading theo cỡ chữ lớn hơn chữ thường."""
    import pymupdf

    doc = pymupdf.open(stream=data, filetype="pdf")
    pages = []  # mỗi trang: list (text, cỡ chữ lớn nhất)
    size_counter: Counter = Counter()
    for page in doc:
        blocks = []
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:  # 0 = khối chữ, 1 = hình ảnh
                continue
            spans = [s for line in block["lines"] for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            text = " ".join(s["text"].strip() for s in spans)
            size = max(round(s["size"], 1) for s in spans)
            for s in spans:
                size_counter[round(s["size"], 1)] += len(s["text"])
            blocks.append((text, size))
        pages.append(blocks)
    doc.close()

    if not size_counter:
        return "", ""
    body_size = size_counter.most_common(1)[0][0]  # cỡ chữ xuất hiện nhiều nhất = chữ thường

    # Dòng lặp lại trên nhiều trang = header/footer (tên tài liệu, số trang...).
    # Thay số bằng "#" trước khi so, vì "Info sheet 1", "Info sheet 2" là cùng một footer.
    def footer_key(text: str) -> str:
        return re.sub(r"\d+", "#", text)

    line_pages = Counter(k for blocks in pages for k in {footer_key(b[0]) for b in blocks})
    repeated = {k for k, n in line_pages.items() if len(pages) >= 3 and n >= len(pages) * 0.5}

    heading_sizes = sorted({size for blocks in pages for text, size in blocks
                            if size >= body_size * 1.2 and len(text) < 120}, reverse=True)
    level_of = {size: min(i + 1, 3) for i, size in enumerate(heading_sizes)}

    lines, title = [], ""
    for blocks in pages:
        for text, size in blocks:
            if footer_key(text) in repeated or re.fullmatch(r"(page\s*)?\d+(\s*of\s*\d+)?", text, re.I):
                continue
            if size in level_of and len(text) < 120:
                title = title or text
                lines.append("#" * level_of[size] + " " + text)
            else:
                text = re.sub(r"^[•●▪◦]\s*", "- ", text)
                lines.append(text)
    return title, "\n\n".join(lines)


# ====================== DOCX ======================

def extract_docx(data: bytes) -> tuple[str, str]:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(io.BytesIO(data))
    lines, title = [], ""
    # Duyệt thân tài liệu theo đúng thứ tự: đoạn văn và bảng xen kẽ
    for child in document.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "tbl":
            table = Table(child, document)
            rows = [" | ".join(c.text.strip() for c in row.cells) for row in table.rows]
            lines.append("\n".join(r for r in rows if r.strip(" |")))
            continue
        if tag != "p":
            continue
        para = Paragraph(child, document)
        text = para.text.strip()
        if not text:
            continue
        style = (para.style.name if para.style is not None else "").lower()
        match = re.match(r"heading (\d)", style)
        if style == "title" or match:
            level = 1 if style == "title" else min(int(match.group(1)), 6)
            title = title or text
            lines.append("#" * level + " " + text)
        elif "list" in style:
            lines.append("- " + text)
        else:
            lines.append(text)
    return title, "\n\n".join(lines)


EXTRACTORS = {"html": extract_html, "pdf": extract_pdf, "docx": extract_docx}


def extract_file(path: Path, doc_type: str) -> tuple[str, str]:
    title, md = EXTRACTORS[doc_type](path.read_bytes())
    return normalize_text(title), normalize_text(md)


# ====================== Chạy ======================

def run(only: str | None = None, force: bool = False) -> int:
    raw_manifest_path = settings.RAW_DIR / "manifest.json"
    if not raw_manifest_path.exists():
        print("Chưa có data/raw/manifest.json — hãy chạy bước 01 trước.")
        return 2
    raw_manifest = read_json(raw_manifest_path)
    out_manifest = read_json(settings.EXTRACT_MANIFEST) if settings.EXTRACT_MANIFEST.exists() else {}

    items = [e for e in raw_manifest.values() if e["status"] == "ok"]
    if only:
        items = [e for e in items if e["id"] == only]

    done = skipped = 0
    problems = []
    for entry in items:
        doc_id = entry["id"]
        out_path = settings.EXTRACTED_DIR / f"{doc_id}.md"
        prev = out_manifest.get(doc_id)
        if not force and prev and prev.get("raw_sha256") == entry["sha256"] and out_path.exists():
            skipped += 1
            continue

        try:
            title, md = extract_file(settings.RAW_DIR / entry["file"], entry["type"])
        except Exception as e:  # file hỏng: ghi nhận rồi làm tiếp tài liệu khác
            problems.append(f"{doc_id}: không đọc được ({e})")
            continue

        n_headings = sum(1 for line in md.split("\n") if line.startswith("#"))
        issues = []
        if len(md) < 300:
            issues.append(f"quá ít nội dung ({len(md)} ký tự)")
        if n_headings == 0:
            issues.append("không có heading nào")
        problems.extend(f"{doc_id}: {i}" for i in issues)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        out_manifest[doc_id] = {
            "id": doc_id, "title": title, "file": out_path.name,
            "raw_sha256": entry["sha256"], "fetched_at": entry["fetched_at"],
            "chars": len(md), "headings": n_headings, "issues": issues,
        }
        done += 1
        print(f"  {doc_id}: {len(md):,} ký tự, {n_headings} heading, tiêu đề: {title[:60]!r}")

    write_json(settings.EXTRACT_MANIFEST, out_manifest)
    print(f"\n02_extract: {done} đã trích, {skipped} bỏ qua (không đổi), {len(problems)} cảnh báo")
    for p in problems:
        print(f"  ! {p}")
    # Chỉ lỗi đọc file mới làm pipeline dừng; thiếu heading chỉ là cảnh báo
    return 1 if any("không đọc được" in p for p in problems) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Bước 02: trích nội dung")
    parser.add_argument("--only")
    parser.add_argument("--force", action="store_true", help="trích lại kể cả khi không đổi")
    parser.add_argument("--sources", help="bỏ qua, chỉ để run_pipeline truyền chung tham số")
    args = parser.parse_args()
    return run(args.only, args.force)


if __name__ == "__main__":
    sys.exit(main())
