"""In ngẫu nhiên vài chunk để đọc bằng mắt.

Câu hỏi khi đọc: "Nếu chỉ thấy đoạn này, mình có hiểu nó nói về gì không?"

Ví dụ:
  python scripts/inspect_chunks.py                  # 5 chunk ngẫu nhiên
  python scripts/inspect_chunks.py --doc fwo_visa_holders --n 3
  python scripts/inspect_chunks.py --file tagged --low   # chỉ chunk tag tin cậy thấp
"""
import argparse
import random
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from lib.io_utils import read_jsonl

FILES = {"chunks": settings.CHUNKS_FILE, "tagged": settings.TAGGED_FILE}


def main() -> int:
    parser = argparse.ArgumentParser(description="Xem ngẫu nhiên vài chunk")
    parser.add_argument("--file", choices=FILES, default="chunks")
    parser.add_argument("--doc", help="chỉ lấy chunk của một doc_id")
    parser.add_argument("--n", type=int, default=5)
    parser.add_argument("--low", action="store_true", help="chỉ chunk có tag tin cậy thấp (file tagged)")
    parser.add_argument("--seed", type=int, help="cố định kết quả ngẫu nhiên")
    args = parser.parse_args()

    path = FILES[args.file]
    if not path.exists():
        print(f"Chưa có {path.name}")
        return 2
    rows = read_jsonl(path)
    if args.doc:
        rows = [r for r in rows if r["doc_id"] == args.doc]
    if args.low:
        rows = [r for r in rows if r.get("tag_confidence") == "low"]
    if not rows:
        print("Không có chunk nào khớp điều kiện.")
        return 1

    random.seed(args.seed)
    for r in random.sample(rows, min(args.n, len(rows))):
        tag = f"  [{r['topic']}/{r['subtopic']}, {r['tag_confidence']}]" if "subtopic" in r else ""
        print("─" * 78)
        print(f"{r['chunk_id']}  {r['doc_id']} #{r['chunk_index']}  {r['tokens']} token{tag}")
        print(f"▸ {r['context_header']}")
        print(textwrap.indent(textwrap.fill(r["content"][:900], 76, replace_whitespace=False), "  "))
    print("─" * 78)
    print(f"{min(args.n, len(rows))}/{len(rows)} chunk")
    return 0


if __name__ == "__main__":
    sys.exit(main())
