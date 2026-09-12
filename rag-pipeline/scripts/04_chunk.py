"""Bước 04 — Chunk: cắt tài liệu sạch thành các đoạn cỡ 300-500 token.

Đầu vào : data/clean/<id>.md + config/sources*.yaml (lấy metadata)
Đầu ra  : data/chunks.jsonl

Nguyên tắc:
  - Cắt theo heading trước: mỗi section (phần dưới một heading) là một đơn vị.
  - Section dài: gom các đoạn văn đến khoảng CHUNK_TARGET_TOKENS rồi cắt,
    chunk sau lặp lại ~CHUNK_OVERLAP_TOKENS cuối của chunk trước.
  - Section quá ngắn: gộp vào chunk trước cùng tài liệu.
  - Contextual chunking: mỗi chunk có context_header dạng
    "Fair Work Ombudsman > Visa holders > Pay and entitlements"
    để khi đứng một mình vẫn biết nó nói về gì.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from lib.io_utils import ConfigError, load_sources, read_json, sha256_bytes, write_jsonl
from lib.text_utils import estimate_tokens, split_long_text, tail_tokens

_HEADING = re.compile(r"^(#{1,6}) (.+)$")


def parse_sections(md: str) -> list[dict]:
    """Chia markdown thành các section, mỗi section nhớ đường dẫn heading của nó.

    Ví dụ: '# A' > '## B' > '### C' cho path ['A', 'B', 'C'].
    Gặp '## D' thì C và B bị đẩy ra khỏi stack, path mới là ['A', 'D'].
    """
    sections: list[dict] = []
    stack: list[tuple[int, str]] = []  # (cấp, tên heading)
    current = {"path": [], "blocks": []}

    for block in (b.strip() for b in md.split("\n\n")):
        if not block:
            continue
        m = _HEADING.match(block)
        if m:
            if current["blocks"]:
                sections.append(current)
            level, text = len(m.group(1)), m.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, text))
            current = {"path": [t for _, t in stack], "blocks": []}
        else:
            current["blocks"].append(block)
    if current["blocks"]:
        sections.append(current)
    return sections


def build_header(source: str, title: str, path: list[str]) -> str:
    parts = [source]
    if title:
        parts.append(title)
    parts.extend(h for h in path if h != title)  # tránh lặp tiêu đề
    return " > ".join(parts)


def chunk_section(blocks: list[str]) -> list[str]:
    """Gom các khối của một section thành các chunk có overlap."""
    target, limit = settings.CHUNK_TARGET_TOKENS, settings.CHUNK_MAX_TOKENS
    overlap = settings.CHUNK_OVERLAP_TOKENS

    pieces: list[str] = []
    for block in blocks:
        if estimate_tokens(block) > limit:
            pieces.extend(split_long_text(block, target))
        else:
            pieces.append(block)

    chunks: list[str] = []
    current: list[str] = []
    for piece in pieces:
        candidate = "\n\n".join(current + [piece])
        if current and estimate_tokens(candidate) > target:
            chunks.append("\n\n".join(current))
            carry = tail_tokens(chunks[-1], overlap)
            # Chỉ thêm overlap nếu không làm chunk mới vượt giới hạn
            fits = carry and estimate_tokens(carry + "\n\n" + piece) <= limit
            current = [carry, piece] if fits else [piece]
        else:
            current.append(piece)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def chunk_document(doc_id: str, md: str, title: str, src: dict, fetched_at: str) -> list[dict]:
    rows: list[dict] = []
    for section in parse_sections(md):
        header = build_header(src["source"], title, section["path"])
        section_text = "\n\n".join(section["blocks"])

        # Section ngắn: gộp vào chunk trước (kèm tên heading để không mất nghĩa)
        if (rows and estimate_tokens(section_text) < settings.CHUNK_MIN_TOKENS):
            label = section["path"][-1] if section["path"] else ""
            merged = rows[-1]["content"] + "\n\n" + (f"{label}\n{section_text}" if label else section_text)
            if estimate_tokens(merged) <= settings.CHUNK_MAX_TOKENS:
                rows[-1]["content"] = merged
                continue

        for text in chunk_section(section["blocks"]):
            rows.append({"context_header": header, "content": text})

    records = []
    for i, row in enumerate(rows):
        key = f"{doc_id}|{row['context_header']}|{row['content']}"
        records.append({
            "chunk_id": sha256_bytes(key.encode("utf-8"))[:16],
            "doc_id": doc_id,
            "chunk_index": i,
            "context_header": row["context_header"],
            "content": row["content"],
            "tokens": estimate_tokens(row["content"]),
            "title": title,
            "url": src["url"],
            "source": src["source"],
            "language": src["language"],
            "topic": src["topic"],  # topic cấp tài liệu; bước 05 có thể chỉnh theo subtopic
            "industry": src["industry"],
            "visa": src["visa"],
            "employment": src["employment"],
            "priority": src["priority"],
            "fetched_at": fetched_at,
        })
    return records


def check_chunks(chunks: list[dict]) -> list[str]:
    errors = []
    ids = [c["chunk_id"] for c in chunks]
    if len(ids) != len(set(ids)):
        errors.append("chunk_id bị trùng")
    for c in chunks:
        if not c["content"].strip():
            errors.append(f"{c['chunk_id']}: chunk rỗng")
        if c["tokens"] > settings.CHUNK_MAX_TOKENS:
            errors.append(f"{c['chunk_id']}: {c['tokens']} token, vượt {settings.CHUNK_MAX_TOKENS}")
        if not c["context_header"]:
            errors.append(f"{c['chunk_id']}: thiếu context_header")
    return errors


def run(sources_path: Path) -> int:
    if not settings.CLEAN_MANIFEST.exists():
        print("Chưa có data/clean/manifest.json — hãy chạy bước 03 trước.")
        return 2
    try:
        sources = {s["id"]: s for s in load_sources(sources_path)}
    except (ConfigError, FileNotFoundError) as e:
        print(f"Lỗi cấu hình: {e}")
        return 2

    clean = read_json(settings.CLEAN_MANIFEST)
    all_chunks, warnings = [], []
    for doc_id, entry in clean.items():
        if entry.get("skip"):
            continue
        if doc_id not in sources:
            warnings.append(f"{doc_id}: không có trong {sources_path.name}, bỏ qua")
            continue
        md = (settings.CLEAN_DIR / entry["file"]).read_text(encoding="utf-8")
        chunks = chunk_document(doc_id, md, entry.get("title", ""), sources[doc_id], entry["fetched_at"])
        if not chunks:
            warnings.append(f"{doc_id}: không tạo được chunk nào")
        all_chunks.extend(chunks)
        print(f"  {doc_id}: {len(chunks)} chunk")

    errors = check_chunks(all_chunks)
    if errors:
        print("LỖI chunk:\n  - " + "\n  - ".join(errors[:20]))
        return 1

    write_jsonl(settings.CHUNKS_FILE, all_chunks)
    tokens = [c["tokens"] for c in all_chunks] or [0]
    print(f"\n04_chunk: {len(clean)} tài liệu → {len(all_chunks)} chunk, "
          f"trung bình {sum(tokens) / len(tokens):.0f} token, "
          f"ngắn nhất {min(tokens)}, dài nhất {max(tokens)}")
    for w in warnings:
        print(f"  ! {w}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Bước 04: cắt chunk")
    parser.add_argument("--sources", type=Path, default=settings.DEFAULT_SOURCES_FILE)
    parser.add_argument("--force", action="store_true", help="bỏ qua (bước này luôn chạy lại)")
    args = parser.parse_args()
    return run(args.sources)


if __name__ == "__main__":
    sys.exit(main())
