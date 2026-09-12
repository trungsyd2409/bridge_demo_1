"""Bước 05 — Tag: gắn subtopic cho từng chunk.

Đầu vào : data/chunks.jsonl, config/taxonomy.yaml
          data/tag_review.csv (nếu có: đọc cột override_subtopic bạn đã sửa tay)
Đầu ra  : data/tagged.jsonl, data/tag_review.csv, data/cache/tags.json

Cách hoạt động:
  - Kế thừa từ nguồn: industry, visa, employment, language (đã có trong chunk).
  - Gemini Flash-Lite chọn subtopic, enum lấy từ taxonomy nên không bịa được.
  - topic = topic chứa subtopic đó (có thể khác topic cấp tài liệu,
    ví dụ trang về visa có đoạn nói về lương -> underpayment).
  - Cache theo chunk_id: chunk không đổi thì không gọi lại Gemini.
  - Sửa tay: mở tag_review.csv bằng Excel, điền cột override_subtopic, lưu,
    rồi chạy lại bước này. Giá trị sửa tay luôn được ưu tiên.
"""
import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from lib import gemini_client
from lib.io_utils import load_taxonomy, read_json, read_jsonl, write_json, write_jsonl

CONFIDENCE = ["high", "medium", "low"]
CSV_FIELDS = ["chunk_id", "doc_id", "doc_topic", "topic", "subtopic", "confidence",
              "override_subtopic", "context_header", "preview"]

SYSTEM_PROMPT = """You label passages from Australian workplace-rights guidance
(Fair Work Ombudsman, Safe Work Australia, Human Rights Commission, Home Affairs)
for a support app used by Vietnamese migrant workers.

For each passage choose exactly ONE subtopic from the allowed list: the thing a worker
would be asking about if this passage is the best answer. The document-level topic is a
hint, not a rule: choose a subtopic from another topic when the passage is clearly about it.
Use confidence "low" when the passage is navigation, generic intro text, or fits no subtopic well."""


def subtopic_index(taxonomy: dict) -> dict[str, str]:
    """{subtopic: topic} — tra ngược topic từ subtopic."""
    return {sub: topic for topic, subs in taxonomy["topics"].items() for sub in subs}


def build_prompt(batch: list[dict], taxonomy: dict) -> str:
    lines = ["Allowed subtopics, grouped by topic:"]
    for topic, subs in taxonomy["topics"].items():
        lines.append(f"- {topic}: {', '.join(subs)}")
    lines.append("\nPassages:")
    for i, c in enumerate(batch):
        lines.append(f"\n[{i}] document topic hint: {c['topic']}\n"
                     f"section: {c['context_header']}\n{c['content'][:1500]}")
    return "\n".join(lines)


def response_schema(all_subtopics: list[str]) -> dict:
    return {
        "type": "ARRAY",
        "items": {
            "type": "OBJECT",
            "properties": {
                "index": {"type": "INTEGER"},
                "subtopic": {"type": "STRING", "enum": all_subtopics},
                "confidence": {"type": "STRING", "enum": CONFIDENCE},
            },
            "required": ["index", "subtopic", "confidence"],
        },
    }


def gemini_tagger(batch: list[dict], taxonomy: dict) -> dict[int, tuple[str, str]]:
    subs = list(subtopic_index(taxonomy))
    result = gemini_client.generate_json(SYSTEM_PROMPT, build_prompt(batch, taxonomy), response_schema(subs))
    out = {}
    for item in result or []:
        idx = item.get("index")
        if isinstance(idx, int) and 0 <= idx < len(batch) and item.get("subtopic") in subs:
            out[idx] = (item["subtopic"], item.get("confidence", "low"))
    return out


def keyword_tagger(batch: list[dict], taxonomy: dict) -> dict[int, tuple[str, str]]:
    """Tagger giả (không gọi API): đếm từ của tên subtopic xuất hiện trong chunk.

    Chỉ dùng cho test và RAG_FAKE_GEMINI=1. Chất lượng thấp, luôn đánh "low".
    """
    out = {}
    for i, c in enumerate(batch):
        text = f"{c['context_header']} {c['content']}".lower()
        best, best_score = None, 0
        for topic, subs in taxonomy["topics"].items():
            for sub in subs:
                counts = [len(re.findall(rf"\b{w}", text)) for w in sub.split("_")]
                # Khớp được nhiều từ KHÁC NHAU quan trọng hơn khớp một từ nhiều lần
                score = 10 * sum(n > 0 for n in counts) + sum(counts)
                score += 0.5 if topic == c["topic"] else 0  # ưu tiên nhẹ topic tài liệu
                if score > best_score:
                    best, best_score = sub, score
        out[i] = (best or taxonomy["topics"][c["topic"]][0], "low")
    return out


def read_overrides(path: Path, valid: set[str]) -> tuple[dict[str, str], list[str]]:
    """Đọc cột override_subtopic từ lần chạy trước (bạn sửa tay trong Excel)."""
    if not path.exists():
        return {}, []
    overrides, warnings = {}, []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            value = (row.get("override_subtopic") or "").strip()
            if not value:
                continue
            if value in valid:
                overrides[row["chunk_id"]] = value
            else:
                warnings.append(f"{row['chunk_id']}: override '{value}' không có trong taxonomy, bỏ qua")
    return overrides, warnings


def write_review_csv(path: Path, rows: list[dict], overrides: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig: thêm BOM để Excel hiển thị đúng tiếng Việt
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        # Đưa dòng cần xem lại lên đầu: tin cậy thấp, hoặc topic khác topic tài liệu
        def order(r):
            return (r["tag_confidence"] != "low", r["topic"] == r["doc_topic"], r["doc_id"], r["chunk_index"])
        for r in sorted(rows, key=order):
            writer.writerow({
                "chunk_id": r["chunk_id"], "doc_id": r["doc_id"], "doc_topic": r["doc_topic"],
                "topic": r["topic"], "subtopic": r["subtopic"], "confidence": r["tag_confidence"],
                "override_subtopic": overrides.get(r["chunk_id"], ""),
                "context_header": r["context_header"],
                "preview": r["content"][:200].replace("\n", " "),
            })


def run(force: bool = False, tagger=None) -> int:
    if not settings.CHUNKS_FILE.exists():
        print("Chưa có data/chunks.jsonl — hãy chạy bước 04 trước.")
        return 2
    taxonomy = load_taxonomy()
    topic_of = subtopic_index(taxonomy)
    chunks = read_jsonl(settings.CHUNKS_FILE)

    if tagger is None:
        tagger = keyword_tagger if gemini_client.is_fake() else gemini_tagger
    model_key = "fake-keywords" if tagger is keyword_tagger else settings.TAG_MODEL

    cache = {} if force or not settings.TAG_CACHE_FILE.exists() else read_json(settings.TAG_CACHE_FILE)
    todo = [c for c in chunks
            if cache.get(c["chunk_id"], {}).get("model") != model_key]
    print(f"  {len(chunks)} chunk, {len(chunks) - len(todo)} lấy từ cache, {len(todo)} cần gắn tag ({model_key})")

    size = settings.TAG_BATCH_SIZE
    n_batches = (len(todo) + size - 1) // size
    failed_batches = 0
    for start in range(0, len(todo), size):
        batch = todo[start:start + size]
        number = start // size + 1
        try:
            labels = tagger(batch, taxonomy)
        except gemini_client.GeminiAuthError as e:
            print(f"\nLỖI API key: {e}")
            return 1  # sai key thì mọi lô đều sẽ lỗi: dừng ngay, không ghi gì
        except Exception as e:
            # Lỗi tạm thời: KHÔNG lưu cache cho lô này, lần chạy sau sẽ thử lại
            failed_batches += 1
            print(f"    lô {number}/{n_batches}: lỗi {str(e)[:200]}")
            continue
        for i, c in enumerate(batch):
            # Model bỏ sót chunk nào thì dùng subtopic đầu tiên của topic tài liệu, đánh "low"
            sub, conf = labels.get(i, (taxonomy["topics"][c["topic"]][0], "low"))
            cache[c["chunk_id"]] = {"subtopic": sub, "confidence": conf, "model": model_key}
        write_json(settings.TAG_CACHE_FILE, cache)  # lưu sau mỗi lô: lỗi giữa chừng không mất công
        print(f"    lô {number}/{n_batches} xong")

    if failed_batches:
        print(f"\n05_tag: {failed_batches}/{n_batches} lô lỗi. Các lô thành công đã lưu cache; "
              "chạy lại lệnh để thử tiếp phần còn thiếu.")
        return 1

    overrides, warnings = read_overrides(settings.TAG_REVIEW_FILE, set(topic_of))
    tagged = []
    for c in chunks:
        cached = cache[c["chunk_id"]]
        sub = overrides.get(c["chunk_id"], cached["subtopic"])
        conf = "manual" if c["chunk_id"] in overrides else cached["confidence"]
        tagged.append({**c, "doc_topic": c["topic"], "topic": topic_of[sub],
                       "subtopic": sub, "tag_confidence": conf})

    write_jsonl(settings.TAGGED_FILE, tagged)
    write_review_csv(settings.TAG_REVIEW_FILE, tagged, overrides)

    by_topic = Counter(t["topic"] for t in tagged)
    low = sum(t["tag_confidence"] == "low" for t in tagged)
    moved = sum(t["topic"] != t["doc_topic"] for t in tagged)
    print(f"\n05_tag: {len(tagged)} chunk, {low} tin cậy thấp, {moved} đổi topic so với tài liệu, "
          f"{len(overrides)} sửa tay")
    print("  theo topic: " + ", ".join(f"{k}={v}" for k, v in by_topic.most_common()))
    empty = [t for t in taxonomy["topics"] if t not in by_topic]
    if empty:
        print(f"  ! topic chưa có chunk nào: {', '.join(empty)}")
    print(f"  Xem lại: {settings.TAG_REVIEW_FILE.name} (dòng cần chú ý nằm ở đầu file)")
    for w in warnings:
        print(f"  ! {w}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Bước 05: gắn tag")
    parser.add_argument("--force", action="store_true", help="bỏ cache, gắn lại toàn bộ")
    parser.add_argument("--sources", help="bỏ qua, chỉ để run_pipeline truyền chung tham số")
    args = parser.parse_args()
    return run(args.force)


if __name__ == "__main__":
    sys.exit(main())
