"""Bước 07 — Build DB: tạo data/rag.db từ data/embedded.jsonl.

Xoá và build lại toàn bộ mỗi lần chạy, nên rag.db luôn là "ảnh chụp" đầy đủ,
không bao giờ còn chunk lỗi thời. Build ra file tạm rồi mới đổi tên:
lỗi giữa chừng không làm hỏng rag.db cũ.
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from lib.io_utils import read_jsonl
from lib.vectors import to_blob

INSERT_CHUNK = """
INSERT INTO rag_chunks (chunk_id, doc_id, content, context_header, url, source, language,
                        topic, subtopic, industry, visa, employment, fetched_at, embedding)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def build(rows: list[dict], out_path: Path) -> dict:
    tmp = out_path.with_suffix(".db.tmp")
    tmp.unlink(missing_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(tmp)
    try:
        conn.executescript(settings.SQL_SCHEMA_FILE.read_text(encoding="utf-8"))
        for r in rows:
            cur = conn.execute(INSERT_CHUNK, (
                r["chunk_id"], r["doc_id"], r["content"], r["context_header"], r["url"],
                r["source"], r["language"], r["topic"], r["subtopic"],
                json.dumps(r["industry"]), json.dumps(r["visa"]), json.dumps(r["employment"]),
                r["fetched_at"], to_blob(r["embedding"]),
            ))
            # rowid của bảng FTS = id của chunk, để nối hai bảng
            conn.execute("INSERT INTO rag_fts (rowid, context_header, content) VALUES (?, ?, ?)",
                         (cur.lastrowid, r["context_header"], r["content"]))

        meta = {
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "chunk_count": str(len(rows)),
            "doc_count": str(len({r["doc_id"] for r in rows})),
            "embed_model": rows[0]["embed_model"] if rows else "",
            "embed_dim": str(settings.EMBED_DIM),
        }
        conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", meta.items())
        conn.commit()

        n_chunks = conn.execute("SELECT count(*) FROM rag_chunks").fetchone()[0]
        n_fts = conn.execute("SELECT count(*) FROM rag_fts").fetchone()[0]
        if not (n_chunks == n_fts == len(rows)):
            raise RuntimeError(f"số dòng lệch: jsonl={len(rows)}, chunks={n_chunks}, fts={n_fts}")
        conn.execute("VACUUM")  # thu gọn file
    finally:
        conn.close()

    tmp.replace(out_path)
    return meta


def run() -> int:
    if not settings.EMBEDDED_FILE.exists():
        print("Chưa có data/embedded.jsonl — hãy chạy bước 06 trước.")
        return 2
    rows = read_jsonl(settings.EMBEDDED_FILE)
    if not rows:
        print("embedded.jsonl rỗng, không có gì để build.")
        return 1
    try:
        meta = build(rows, settings.DB_FILE)
    except (sqlite3.Error, RuntimeError, ValueError) as e:
        print(f"LỖI build: {e}")
        return 1

    size_mb = settings.DB_FILE.stat().st_size / 1024 / 1024
    print(f"07_build_db: {meta['chunk_count']} chunk từ {meta['doc_count']} tài liệu → "
          f"{settings.DB_FILE.name} ({size_mb:.2f} MB), model {meta['embed_model']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Bước 07: build rag.db")
    parser.add_argument("--sources", help="bỏ qua, chỉ để run_pipeline truyền chung tham số")
    parser.add_argument("--force", action="store_true", help="bỏ qua (bước này luôn build lại)")
    parser.parse_args()
    return run()


if __name__ == "__main__":
    sys.exit(main())
