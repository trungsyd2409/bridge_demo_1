"""Bước 03 — Clean: chuẩn hoá và bỏ phần rác khỏi Markdown.

Đầu vào : data/extracted/<id>.md
Đầu ra  : data/clean/<id>.md + data/clean/manifest.json

Việc làm:
  1. Chuẩn hoá Unicode NFC, gộp khoảng trắng
  2. Xoá dòng khớp mẫu trong config/boilerplate.yaml
  3. Xoá dòng trùng liên tiếp
  4. Xoá heading rỗng (heading không có nội dung bên dưới)
  5. Phát hiện hai tài liệu có nội dung giống hệt nhau
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from lib.io_utils import read_json, read_yaml, sha256_bytes, write_json
from lib.text_utils import normalize_text

BOILERPLATE_FILE = settings.CONFIG_DIR / "boilerplate.yaml"
_HEADING = re.compile(r"^(#{1,6}) ")


def load_patterns(path: Path = BOILERPLATE_FILE) -> list[re.Pattern]:
    raw = read_yaml(path)["line_patterns"]
    return [re.compile(rf"^\s*{p}\s*[.:]?\s*$", re.I) for p in raw]


def heading_level(line: str) -> int:
    """Số dấu # ở đầu dòng; 0 = không phải heading."""
    m = _HEADING.match(line)
    return len(m.group(1)) if m else 0


def remove_empty_sections(blocks: list[str]) -> list[str]:
    """Bỏ heading mà ngay sau nó là heading cùng cấp/cao hơn, hoặc hết tài liệu.

    '## A' rồi '## B'  -> A rỗng, bỏ A.
    '## A' rồi '### A1' -> giữ A (A1 là nội dung con của A).
    Lặp đến khi không đổi, vì bỏ một heading có thể làm lộ heading rỗng khác.
    """
    changed = True
    while changed:
        changed = False
        kept = []
        for i, block in enumerate(blocks):
            level = heading_level(block)
            if level:
                nxt = blocks[i + 1] if i + 1 < len(blocks) else None
                nxt_level = heading_level(nxt) if nxt is not None else 0
                if nxt is None or (nxt_level and nxt_level <= level):
                    changed = True
                    continue
            kept.append(block)
        blocks = kept
    return blocks


def clean_markdown(md: str, patterns: list[re.Pattern]) -> tuple[str, int]:
    """Trả về (markdown sạch, số khối đã xoá)."""
    blocks = [b.strip() for b in normalize_text(md).split("\n\n") if b.strip()]
    before = len(blocks)

    kept: list[str] = []
    for block in blocks:
        # Khối nhiều dòng (ví dụ bảng): xoá từng dòng rác bên trong
        lines = [ln for ln in block.split("\n") if not any(p.match(ln) for p in patterns)]
        block = "\n".join(lines).strip()
        if not block:
            continue
        # Bỏ heading chỉ còn dấu #
        if heading_level(block) and not block.lstrip("#").strip():
            continue
        if kept and kept[-1] == block:  # trùng liên tiếp
            continue
        kept.append(block)

    kept = remove_empty_sections(kept)
    return "\n\n".join(kept), before - len(kept)


def run(only: str | None = None) -> int:
    if not settings.EXTRACT_MANIFEST.exists():
        print("Chưa có data/extracted/manifest.json — hãy chạy bước 02 trước.")
        return 2
    extracted = read_json(settings.EXTRACT_MANIFEST)
    patterns = load_patterns()

    items = [e for e in extracted.values() if not only or e["id"] == only]
    manifest = read_json(settings.CLEAN_MANIFEST) if (only and settings.CLEAN_MANIFEST.exists()) else {}
    seen_hash: dict[str, str] = {e["sha256"]: k for k, e in manifest.items() if "sha256" in e}
    warnings = []

    for entry in items:
        doc_id = entry["id"]
        md = (settings.EXTRACTED_DIR / entry["file"]).read_text(encoding="utf-8")
        clean, removed = clean_markdown(md, patterns)
        digest = sha256_bytes(clean.encode("utf-8"))

        duplicate_of = seen_hash.get(digest)
        if duplicate_of and duplicate_of != doc_id:
            warnings.append(f"{doc_id}: nội dung giống hệt {duplicate_of}, bỏ qua")
            manifest[doc_id] = {**entry, "duplicate_of": duplicate_of, "skip": True}
            continue
        seen_hash[digest] = doc_id

        out = settings.CLEAN_DIR / f"{doc_id}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(clean, encoding="utf-8")
        pct = 100 * (1 - len(clean) / max(len(md), 1))
        manifest[doc_id] = {**entry, "file": out.name, "sha256": digest, "skip": False,
                            "chars": len(clean), "blocks_removed": removed}
        print(f"  {doc_id}: {len(md):,} → {len(clean):,} ký tự (-{pct:.0f}%), xoá {removed} khối")
        if pct > 50:
            warnings.append(f"{doc_id}: xoá hơn 50% nội dung, kiểm tra lại boilerplate.yaml")

    write_json(settings.CLEAN_MANIFEST, manifest)
    kept = sum(1 for e in manifest.values() if not e.get("skip"))
    print(f"\n03_clean: {kept} tài liệu sạch, {len(warnings)} cảnh báo")
    for w in warnings:
        print(f"  ! {w}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Bước 03: làm sạch")
    parser.add_argument("--only")
    parser.add_argument("--sources", help="bỏ qua, chỉ để run_pipeline truyền chung tham số")
    parser.add_argument("--force", action="store_true", help="bỏ qua (bước này luôn chạy lại)")
    args = parser.parse_args()
    return run(args.only)


if __name__ == "__main__":
    sys.exit(main())
