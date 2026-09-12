"""Gõ câu hỏi, xem ngay kết quả tìm kiếm trong rag.db.

In hạng của cả hai nhánh (vector, keyword) và điểm RRF, để thấy mỗi nhánh đóng góp gì.

Ví dụ:
  python scripts/search_cli.py "employer does not give pay slips"
  python scripts/search_cli.py --vi "chủ không đưa payslip"          # dịch VI→EN như NLU
  python scripts/search_cli.py "work hours limit" --visa student --k 3
"""
import argparse
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from lib import gemini_client
from lib.search import Filters, RagIndex

TRANSLATE_PROMPT = (
    "Rewrite this Vietnamese question from a migrant worker in Australia as a short English "
    "search query using Australian workplace law terms (award, casual loading, pay slip, "
    "underpayment, visa conditions...). Return JSON only."
)


def to_english(question: str) -> str:
    if gemini_client.is_fake():
        print("  (chế độ giả: không dịch, dùng nguyên câu)")
        return question
    result = gemini_client.generate_json(
        TRANSLATE_PROMPT, question,
        {"type": "OBJECT", "properties": {"englishQuery": {"type": "STRING"}}, "required": ["englishQuery"]},
    )
    return result["englishQuery"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Tìm thử trong rag.db")
    parser.add_argument("query")
    parser.add_argument("--vi", action="store_true", help="câu hỏi tiếng Việt: dịch sang tiếng Anh trước")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--topic", action="append", help="lọc topic (dùng nhiều lần được)")
    parser.add_argument("--visa")
    parser.add_argument("--industry")
    parser.add_argument("--employment")
    parser.add_argument("--full", action="store_true", help="in toàn bộ nội dung chunk")
    args = parser.parse_args()

    if not settings.DB_FILE.exists():
        print("Chưa có data/rag.db — hãy chạy pipeline đến bước 07.")
        return 2

    query = to_english(args.query) if args.vi else args.query
    if args.vi:
        print(f"englishQuery: {query}")
    filters = Filters(topics=args.topic, visa=args.visa, industry=args.industry, employment=args.employment)
    has_filter = any([args.topic, args.visa, args.industry, args.employment])

    index = RagIndex(settings.DB_FILE)
    try:
        qvec = gemini_client.embed([query], gemini_client.TASK_QUERY)[0]
        hits = index.hybrid_search(qvec, query, args.k, filters if has_filter else None)
    finally:
        index.close()

    if not hits:
        print("Không có kết quả.")
        return 0
    print(f"\n{'#':>2}  {'RRF':>6}  {'cosine':>6}  {'hạng vec':>8}  {'hạng BM25':>9}  topic/subtopic")
    for i, h in enumerate(hits, start=1):
        cos = f"{h.vector_score:.3f}" if h.vector_score is not None else "-"
        vr = str(h.vector_rank or "-")
        kr = str(h.keyword_rank or "-")
        print(f"{i:>2}  {h.rrf_score:.4f}  {cos:>6}  {vr:>8}  {kr:>9}  {h.topic}/{h.subtopic}")
        print(f"    ▸ {h.context_header}")
        body = h.content if args.full else h.content[:220].replace("\n", " ") + "…"
        print(textwrap.indent(textwrap.fill(body, 74), "      "))
        print(f"      {h.url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
