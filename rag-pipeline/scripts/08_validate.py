"""Bước 08 — Validate: kiểm tra rag.db và đo chất lượng tìm kiếm.

Phần A — Dữ liệu (sai là dừng, mã thoát 1):
  số chiều, độ dài vector, tag hợp lệ, số dòng FTS khớp, không chunk rỗng...
Phần B — Chất lượng (chỉ báo cáo, trừ khi đặt --min-recall):
  chạy các câu trong eval/questions.jsonl, đo Recall@k và MRR cho
  3 cách tìm: vector, keyword (BM25), hybrid (RRF).

Mỗi dòng eval/questions.jsonl:
  {"id": "q01", "question_vi": "...", "english_query": "...",
   "expected_doc_ids": ["fwo_visa_holders"], "filters": {"visa": "student"}}
  - english_query: câu mà NLU sẽ tạo ra (bước dịch nằm ở app, không đo ở đây)
  - filters: tuỳ chọn, cùng tên trường với lib.search.Filters
  Câu nào tài liệu mong đợi chưa có trong rag.db sẽ được bỏ qua (khi chạy bộ mẫu).
"""
import argparse
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from config import settings
from lib import gemini_client
from lib.io_utils import load_taxonomy, read_jsonl
from lib.search import Filters, RagIndex

METHODS = ["vector", "keyword", "hybrid"]


# ====================== A. Dữ liệu ======================

def check_data(index: RagIndex, taxonomy: dict) -> tuple[list[str], list[str], dict]:
    errors, warnings = [], []
    meta = index.meta
    if meta.get("embed_dim") != str(settings.EMBED_DIM):
        errors.append(f"meta.embed_dim={meta.get('embed_dim')}, cần {settings.EMBED_DIM}")
    if meta.get("embed_model", "").startswith("fake"):
        warnings.append("rag.db đang dùng vector GIẢ (RAG_FAKE_GEMINI=1) — đừng publish bản này")

    conn = index.conn
    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        errors.append("SQLite integrity_check thất bại")
    n_chunks = conn.execute("SELECT count(*) FROM rag_chunks").fetchone()[0]
    n_fts = conn.execute("SELECT count(*) FROM rag_fts").fetchone()[0]
    if n_chunks != n_fts:
        errors.append(f"rag_chunks={n_chunks} nhưng rag_fts={n_fts}")
    if str(n_chunks) != meta.get("chunk_count"):
        errors.append(f"meta.chunk_count={meta.get('chunk_count')} khác số dòng thật {n_chunks}")

    if len(index.rows):
        norms = np.linalg.norm(index.matrix, axis=1)
        bad = int(np.sum(np.abs(norms - 1) > settings.NORM_TOLERANCE))
        if bad:
            errors.append(f"{bad} vector có độ dài khác 1 — thiếu chuẩn hoá L2")

    topic_of = {s: t for t, subs in taxonomy["topics"].items() for s in subs}
    for r in index.rows:
        cid = r["chunk_id"]
        if not r["content"].strip():
            errors.append(f"{cid}: nội dung rỗng")
        if topic_of.get(r["subtopic"]) != r["topic"]:
            errors.append(f"{cid}: subtopic '{r['subtopic']}' không thuộc topic '{r['topic']}'")
        if r["language"] not in taxonomy["language"]:
            errors.append(f"{cid}: language '{r['language']}' không hợp lệ")
        for key in ("industry", "visa", "employment"):
            if not r[key] or any(v not in taxonomy[key] for v in r[key]):
                errors.append(f"{cid}: {key}={r[key]} không hợp lệ")

    by_topic = Counter(r["topic"] for r in index.rows)
    missing = [t for t in taxonomy["topics"] if t not in by_topic]
    if missing:
        warnings.append(f"topic chưa có chunk: {', '.join(missing)}")
    stats = {"chunks": n_chunks, "docs": len({r["doc_id"] for r in index.rows}),
             "by_topic": dict(by_topic.most_common()), "meta": meta}
    return errors, warnings, stats


# ====================== B. Chất lượng ======================

def first_hit_rank(doc_ids: list[str], expected: set[str]) -> int | None:
    for rank, d in enumerate(doc_ids, start=1):
        if d in expected:
            return rank
    return None


def evaluate(index: RagIndex, questions: list[dict], k: int) -> tuple[dict, list[dict], list[str]]:
    available = {r["doc_id"] for r in index.rows}
    usable, skipped = [], []
    for q in questions:
        if set(q["expected_doc_ids"]) & available:
            usable.append(q)
        else:
            skipped.append(q["id"])
    if not usable:
        return {}, [], skipped

    vectors = gemini_client.embed([q["english_query"] for q in usable], gemini_client.TASK_QUERY)
    details = []
    for q, qvec in zip(usable, vectors):
        f = Filters(**q.get("filters", {})) if q.get("filters") else None
        expected = set(q["expected_doc_ids"])
        ranked = {
            "vector": index.doc_ids([cid for cid, _ in index.vector_search(qvec, k, f)]),
            "keyword": index.doc_ids(index.keyword_search(q["english_query"], k, f)),
            "hybrid": [h.doc_id for h in index.hybrid_search(qvec, q["english_query"], k, f)],
        }
        details.append({"id": q["id"], "question": q.get("question_vi", ""),
                        "expected": sorted(expected), "top": ranked["hybrid"],
                        **{m: first_hit_rank(ranked[m], expected) for m in METHODS}})

    n = len(details)
    metrics = {}
    for m in METHODS:
        ranks = [d[m] for d in details]
        metrics[m] = {
            "recall": sum(r is not None for r in ranks) / n,
            "mrr": sum(1 / r for r in ranks if r) / n,  # hạng 1 → 1.0, hạng 2 → 0.5 ...
        }
    return metrics, details, skipped


# ====================== Báo cáo ======================

def write_report(stats, errors, warnings, metrics, details, skipped, k) -> Path:
    now = datetime.now()
    lines = [f"# Báo cáo validate — {now:%Y-%m-%d %H:%M}", "",
             f"- Chunk: {stats['chunks']} từ {stats['docs']} tài liệu",
             f"- Model: {stats['meta'].get('embed_model')} ({stats['meta'].get('embed_dim')} chiều)",
             f"- Build lúc: {stats['meta'].get('built_at')}", "",
             "## Chunk theo topic", ""]
    lines += [f"- {t}: {n}" for t, n in stats["by_topic"].items()]
    lines += ["", "## Kiểm tra dữ liệu", ""]
    lines += [f"- ✗ {e}" for e in errors] or ["- ✓ Không có lỗi"]
    lines += [f"- ! {w}" for w in warnings]
    if metrics:
        lines += ["", f"## Chất lượng tìm kiếm ({len(details)} câu, top {k})", "",
                  "| Cách tìm | Recall@k | MRR |", "|---|---|---|"]
        lines += [f"| {m} | {metrics[m]['recall']:.0%} | {metrics[m]['mrr']:.2f} |" for m in METHODS]
        lines += ["", "## Chi tiết từng câu (hạng của tài liệu đúng, - = không có trong top)", "",
                  "| id | câu hỏi | vector | keyword | hybrid | top hybrid |", "|---|---|---|---|---|---|"]
        for d in details:
            fmt = lambda r: str(r) if r else "-"
            lines.append(f"| {d['id']} | {d['question'][:50]} | {fmt(d['vector'])} | "
                         f"{fmt(d['keyword'])} | {fmt(d['hybrid'])} | {', '.join(d['top'][:3])} |")
    if skipped:
        lines += ["", f"Bỏ qua {len(skipped)} câu (tài liệu chưa có trong rag.db): {', '.join(skipped)}"]

    settings.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = settings.REPORTS_DIR / f"validate_{now:%Y%m%d_%H%M%S}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run(k: int, min_recall: float | None) -> int:
    if not settings.DB_FILE.exists():
        print("Chưa có data/rag.db — hãy chạy bước 07 trước.")
        return 2
    index = RagIndex(settings.DB_FILE)
    try:
        errors, warnings, stats = check_data(index, load_taxonomy())
        questions = read_jsonl(settings.EVAL_FILE) if settings.EVAL_FILE.exists() else []
        metrics, details, skipped = evaluate(index, questions, k) if questions else ({}, [], [])
    finally:
        index.close()

    report = write_report(stats, errors, warnings, metrics, details, skipped, k)
    print(f"08_validate: {stats['chunks']} chunk, {len(errors)} lỗi dữ liệu, {len(warnings)} cảnh báo")
    for e in errors[:10]:
        print(f"  ✗ {e}")
    for w in warnings:
        print(f"  ! {w}")
    if metrics:
        print(f"  Chất lượng ({len(details)} câu, top {k}, bỏ qua {len(skipped)}):")
        for m in METHODS:
            print(f"    {m:8s} Recall@{k} {metrics[m]['recall']:.0%}   MRR {metrics[m]['mrr']:.2f}")
    elif questions:
        print(f"  Không câu eval nào dùng được (bỏ qua {len(skipped)}): tài liệu mong đợi chưa có trong rag.db")
    else:
        print(f"  Chưa có {settings.EVAL_FILE.name}: bỏ qua đo chất lượng")
    try:
        shown = report.relative_to(settings.ROOT)
    except ValueError:  # báo cáo nằm ngoài thư mục dự án (ví dụ khi test)
        shown = report
    print(f"  Báo cáo: {shown}")

    if errors:
        return 1
    if min_recall is not None and metrics and metrics["hybrid"]["recall"] < min_recall:
        print(f"  ✗ Recall hybrid {metrics['hybrid']['recall']:.0%} thấp hơn ngưỡng {min_recall:.0%}")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Bước 08: kiểm tra và đo chất lượng")
    parser.add_argument("--k", type=int, default=settings.EVAL_TOP_K)
    parser.add_argument("--min-recall", type=float, help="ví dụ 0.8: dừng nếu recall hybrid thấp hơn")
    parser.add_argument("--sources", help="bỏ qua, chỉ để run_pipeline truyền chung tham số")
    parser.add_argument("--force", action="store_true", help="bỏ qua")
    args = parser.parse_args()
    return run(args.k, args.min_recall)


if __name__ == "__main__":
    sys.exit(main())
