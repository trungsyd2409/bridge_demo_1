"""Chạy nhiều bước liên tiếp. Bước nào lỗi (mã thoát khác 0) thì dừng ngay.

Ví dụ:
  python scripts/run_pipeline.py --sources config/sources.sample.yaml   # bước 01 → 08
  python scripts/run_pipeline.py --from 5                               # sửa tag xong, chạy 05 → 08
  python scripts/run_pipeline.py --from 1 --to 9                        # gồm cả publish

Mặc định dừng ở bước 08: publish (09) là việc có chủ đích, phải gọi --to 9.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STEPS = {
    1: "01_fetch.py", 2: "02_extract.py", 3: "03_clean.py", 4: "04_chunk.py",
    5: "05_tag.py", 6: "06_embed.py", 7: "07_build_db.py", 8: "08_validate.py",
    9: "09_publish.py",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Chạy pipeline RAG")
    parser.add_argument("--from", dest="start", type=int, default=1, choices=STEPS)
    parser.add_argument("--to", dest="end", type=int, default=8, choices=STEPS)
    parser.add_argument("--sources", help="file nguồn, ví dụ config/sources.sample.yaml")
    parser.add_argument("--force", action="store_true", help="bỏ cache ở mọi bước")
    args = parser.parse_args()

    extra = []
    if args.sources:
        extra += ["--sources", args.sources]
    if args.force:
        extra.append("--force")

    started = time.time()
    for number in range(args.start, args.end + 1):
        script = STEPS[number]
        print(f"\n{'=' * 60}\n▶ Bước {number:02d}: {script}\n{'=' * 60}")
        t0 = time.time()
        code = subprocess.call([sys.executable, str(ROOT / "scripts" / script), *extra], cwd=ROOT)
        if code != 0:
            print(f"\n✗ Dừng ở bước {number:02d} (mã thoát {code}). Sửa lỗi rồi chạy lại: "
                  f"python scripts/run_pipeline.py --from {number}")
            return code
        print(f"  ({time.time() - t0:.1f}s)")

    print(f"\n✓ Xong bước {args.start:02d} → {args.end:02d} trong {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
