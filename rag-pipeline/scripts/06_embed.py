"""Bước 06 — Embed: tạo vector 768 chiều cho từng chunk.

Đầu vào : data/tagged.jsonl
Đầu ra  : data/embedded.jsonl (thêm trường "embedding")

Văn bản được embed = context_header + nội dung, để vector mang cả ngữ cảnh.
Cache: chunk_id đã có vector (cùng model, cùng số chiều) trong embedded.jsonl
cũ thì dùng lại, không gọi Gemini.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from config import settings
from lib import gemini_client
from lib.io_utils import read_jsonl, write_jsonl


def embed_text(chunk: dict) -> str:
    return f"{chunk['context_header']}\n\n{chunk['content']}"


def model_key() -> str:
    return "fake-hashing" if gemini_client.is_fake() else settings.EMBED_MODEL


def check_vectors(matrix: np.ndarray) -> list[str]:
    """Kiểm tra ma trận vector: đúng số chiều, không NaN, độ dài ≈ 1."""
    errors = []
    if matrix.ndim != 2 or matrix.shape[1] != settings.EMBED_DIM:
        return [f"kích thước {matrix.shape}, cần (n, {settings.EMBED_DIM})"]
    if not np.isfinite(matrix).all():
        errors.append("có giá trị NaN/vô cực")
    norms = np.linalg.norm(matrix, axis=1)
    bad = np.where(np.abs(norms - 1.0) > settings.NORM_TOLERANCE)[0]
    if len(bad):
        errors.append(f"{len(bad)} vector có độ dài khác 1 (ví dụ {norms[bad[0]]:.3f}) — thiếu chuẩn hoá L2")
    return errors


def load_cache(force: bool) -> dict[str, list[float]]:
    if force or not settings.EMBEDDED_FILE.exists():
        return {}
    key = model_key()
    return {r["chunk_id"]: r["embedding"] for r in read_jsonl(settings.EMBEDDED_FILE)
            if r.get("embed_model") == key and len(r.get("embedding", [])) == settings.EMBED_DIM}


def run(force: bool = False) -> int:
    if not settings.TAGGED_FILE.exists():
        print("Chưa có data/tagged.jsonl — hãy chạy bước 05 trước.")
        return 2
    chunks = read_jsonl(settings.TAGGED_FILE)
    cache = load_cache(force)
    todo = [c for c in chunks if c["chunk_id"] not in cache]
    print(f"  {len(chunks)} chunk, {len(chunks) - len(todo)} lấy từ cache, "
          f"{len(todo)} cần embed ({model_key()}, {settings.EMBED_DIM} chiều)")

    size = settings.EMBED_BATCH_SIZE
    for start in range(0, len(todo), size):
        batch = todo[start:start + size]
        try:
            matrix = gemini_client.embed([embed_text(c) for c in batch], gemini_client.TASK_DOCUMENT)
        except gemini_client.GeminiAuthError as e:
            print(f"\nLỖI API key: {e}")
            return 1
        except Exception as e:
            # Vector đã tạo ở các lô trước chưa được ghi: lưu tạm để lần sau không mất công
            write_jsonl(settings.EMBEDDED_FILE, [
                {**c, "embed_model": model_key(), "embedding": cache[c["chunk_id"]]}
                for c in chunks if c["chunk_id"] in cache])
            print(f"\nLỖI embed ở lô {start // size + 1}: {str(e)[:300]}")
            print("  Đã lưu các vector tạo được. Chạy lại để tiếp tục. "
                  "Nếu lỗi nói về số lượng nội dung mỗi lần gọi, giảm EMBED_BATCH_SIZE trong settings.py.")
            return 1
        errors = check_vectors(matrix)
        if errors:  # dừng ngay, không ghi vector sai
            print("LỖI vector: " + "; ".join(errors))
            return 1
        for c, vec in zip(batch, matrix):
            cache[c["chunk_id"]] = [round(float(x), 7) for x in vec]
        print(f"    lô {start // size + 1}/{(len(todo) + size - 1) // size} xong")

    rows = [{**c, "embed_model": model_key(), "embedding": cache[c["chunk_id"]]} for c in chunks]
    errors = check_vectors(np.array([r["embedding"] for r in rows], dtype=np.float32))
    if errors:
        print("LỖI vector: " + "; ".join(errors))
        return 1

    write_jsonl(settings.EMBEDDED_FILE, rows)
    print(f"\n06_embed: {len(rows)} vector, {settings.EMBED_DIM} chiều, độ dài ≈ 1 ✓")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Bước 06: tạo embedding")
    parser.add_argument("--force", action="store_true", help="bỏ cache, embed lại toàn bộ")
    parser.add_argument("--sources", help="bỏ qua, chỉ để run_pipeline truyền chung tham số")
    args = parser.parse_args()
    return run(args.force)


if __name__ == "__main__":
    sys.exit(main())
