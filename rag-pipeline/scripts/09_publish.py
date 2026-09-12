"""Bước 09 — Publish: kiểm tra lần cuối rồi copy rag.db sang project Next.js.

Cách chạy:
  python scripts/09_publish.py                       # đích mặc định: settings.APP_DB_PATH
  python scripts/09_publish.py --to ../app/data/rag.db
"""
import argparse
import importlib
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from lib.io_utils import load_taxonomy
from lib.search import RagIndex

validate = importlib.import_module("scripts.08_validate")


def run(target: Path, allow_fake: bool = False) -> int:
    if not settings.DB_FILE.exists():
        print("Chưa có data/rag.db — hãy chạy bước 07 trước.")
        return 2

    index = RagIndex(settings.DB_FILE)
    try:
        errors, _, stats = validate.check_data(index, load_taxonomy())
    finally:
        index.close()

    model = stats["meta"].get("embed_model", "")
    if model.startswith("fake") and not allow_fake:
        print("Từ chối publish: rag.db dùng vector GIẢ. Chạy lại bước 06-07 với Gemini thật "
              "(bỏ RAG_FAKE_GEMINI), hoặc thêm --allow-fake nếu chỉ thử luồng.")
        return 1
    if errors:
        print(f"Từ chối publish: {len(errors)} lỗi dữ liệu. Chạy bước 08 để xem chi tiết.")
        return 1
    if not target.parent.exists():
        print(f"Không thấy thư mục đích {target.parent}. Tạo thư mục đó hoặc dùng --to.")
        return 2

    tmp = target.with_suffix(".db.tmp")
    shutil.copy2(settings.DB_FILE, tmp)
    tmp.replace(target)  # thay thế một lần, app không bao giờ đọc phải file copy dở

    size_mb = target.stat().st_size / 1024 / 1024
    print(f"09_publish: {stats['chunks']} chunk ({size_mb:.2f} MB, {model}) → {target}")
    print("  Nhớ: khai báo data/rag.db trong outputFileTracingIncludes của next.config "
          "để Vercel đóng gói file này, rồi commit và deploy.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Bước 09: copy rag.db sang app")
    parser.add_argument("--to", type=Path, default=settings.APP_DB_PATH)
    parser.add_argument("--allow-fake", action="store_true")
    parser.add_argument("--sources", help="bỏ qua, chỉ để run_pipeline truyền chung tham số")
    parser.add_argument("--force", action="store_true", help="bỏ qua")
    args = parser.parse_args()
    return run(args.to, args.allow_fake)


if __name__ == "__main__":
    sys.exit(main())
