"""Tìm kiếm trong rag.db: vector + từ khoá (BM25) + lọc metadata + RRF.

Đây là logic THAM CHIẾU: app Next.js sẽ viết lại bằng TypeScript y như vậy.
Bước 08 đo chất lượng bằng chính module này, nên con số Recall phản ánh app thật.

Luồng:
  câu hỏi tiếng Anh ──► vector_search (cosine)  ──┐
                   └──► keyword_search (BM25)   ──┴─► rrf() ──► top k
  Cả hai nhánh áp dụng cùng một bộ lọc (topic, visa, ngành, hình thức làm việc).
"""
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from config import settings
from lib.vectors import from_blob

RRF_K = 60
_WORD = re.compile(r"[a-zA-ZÀ-ỹ0-9]+")
STOPWORDS = {
    "a", "an", "the", "is", "are", "am", "was", "were", "be", "been", "do", "does", "did",
    "i", "me", "my", "you", "your", "he", "she", "it", "we", "they", "them", "their",
    "to", "of", "in", "on", "at", "for", "with", "and", "or", "but", "if", "so", "not",
    "can", "could", "should", "would", "will", "what", "when", "where", "who", "how", "why",
    "this", "that", "these", "those", "there", "have", "has", "had", "about", "from", "by",
}


@dataclass
class Filters:
    """Bộ lọc. Để None = không lọc trường đó.

    topics / languages: danh sách giá trị chấp nhận.
    industry / visa / employment: MỘT giá trị từ hồ sơ onboarding của người dùng;
      chunk khớp nếu danh sách của nó chứa giá trị đó hoặc chứa "all".
    """
    topics: list[str] | None = None
    languages: list[str] | None = None
    industry: str | None = None
    visa: str | None = None
    employment: str | None = None


@dataclass
class Hit:
    chunk_id: str
    doc_id: str
    context_header: str
    content: str
    url: str
    source: str
    topic: str
    subtopic: str
    vector_score: float | None = None
    vector_rank: int | None = None
    keyword_rank: int | None = None
    rrf_score: float = 0.0
    extra: dict = field(default_factory=dict)


def rrf(ranked_lists: list[list[int]], k: int = RRF_K) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion: điểm = tổng 1 / (k + thứ hạng), thứ hạng bắt đầu từ 1."""
    scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


def build_fts_query(text: str) -> str:
    """Biến câu hỏi thành truy vấn FTS5 an toàn: các từ khoá nối bằng OR.

    Đặt mỗi từ trong ngoặc kép để ký tự đặc biệt (-, :, *) không làm lỗi cú pháp FTS5.
    """
    seen, words = set(), []
    for w in _WORD.findall(text.lower()):
        if len(w) < 2 or w in STOPWORDS or w in seen:
            continue
        seen.add(w)
        words.append(f'"{w}"')
    return " OR ".join(words)


class RagIndex:
    """Mở rag.db một lần, nạp toàn bộ vector vào bộ nhớ (giống cách app sẽ làm)."""

    def __init__(self, db_path: Path | None = None):
        db_path = db_path or settings.DB_FILE  # đọc lúc chạy, không phải lúc import
        self.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)  # chỉ đọc
        self.conn.row_factory = sqlite3.Row
        self.meta = dict(self.conn.execute("SELECT key, value FROM meta").fetchall())
        rows = self.conn.execute(
            "SELECT id, chunk_id, doc_id, context_header, content, url, source, language, "
            "topic, subtopic, industry, visa, employment, embedding FROM rag_chunks ORDER BY id"
        ).fetchall()
        self.rows = [dict(r) for r in rows]
        for r in self.rows:
            for key in ("industry", "visa", "employment"):
                r[key] = json.loads(r[key])
        self.ids = np.array([r["id"] for r in self.rows])
        self.pos_of_id = {r["id"]: i for i, r in enumerate(self.rows)}
        self.matrix = (np.stack([from_blob(r.pop("embedding")) for r in self.rows])
                       if self.rows else np.zeros((0, settings.EMBED_DIM), dtype=np.float32))

    def close(self) -> None:
        self.conn.close()

    # ---------- lọc ----------

    def _matches(self, r: dict, f: Filters) -> bool:
        if f.topics and r["topic"] not in f.topics:
            return False
        if f.languages and r["language"] not in f.languages:
            return False
        for key in ("industry", "visa", "employment"):
            wanted = getattr(f, key)
            if wanted and "all" not in r[key] and wanted not in r[key]:
                return False
        return True

    def _mask(self, f: Filters | None) -> np.ndarray:
        if f is None:
            return np.ones(len(self.rows), dtype=bool)
        return np.array([self._matches(r, f) for r in self.rows], dtype=bool)

    # ---------- hai nhánh tìm kiếm ----------

    def vector_search(self, query_vec: np.ndarray, k: int, f: Filters | None = None) -> list[tuple[int, float]]:
        """Trả về [(id, cosine)] giảm dần. Vector đã chuẩn hoá nên cosine = tích vô hướng."""
        if not self.rows:
            return []
        scores = self.matrix @ np.asarray(query_vec, dtype=np.float32).reshape(-1)
        scores[~self._mask(f)] = -np.inf
        order = np.argsort(-scores)[:k]
        return [(int(self.ids[i]), float(scores[i])) for i in order if np.isfinite(scores[i])]

    def keyword_search(self, query: str, k: int, f: Filters | None = None) -> list[int]:
        """Trả về [id] theo BM25. bm25() của SQLite: điểm càng ÂM càng liên quan."""
        fts_query = build_fts_query(query)
        if not fts_query:
            return []
        # Heading nặng hơn nội dung: trùng từ trong tiêu đề là tín hiệu mạnh
        rows = self.conn.execute(
            "SELECT rowid FROM rag_fts WHERE rag_fts MATCH ? "
            "ORDER BY bm25(rag_fts, 2.0, 1.0) LIMIT ?",
            (fts_query, k * 5),  # lấy dư rồi lọc metadata trong Python
        ).fetchall()
        mask = self._mask(f)
        return [r[0] for r in rows if mask[self.pos_of_id[r[0]]]][:k]

    # ---------- hybrid ----------

    def hybrid_search(self, query_vec: np.ndarray, query_text: str, k: int = 5,
                      f: Filters | None = None, candidates: int = 20) -> list[Hit]:
        vec = self.vector_search(query_vec, candidates, f)
        kw = self.keyword_search(query_text, candidates, f)
        vec_score = dict(vec)
        vec_rank = {cid: i for i, (cid, _) in enumerate(vec, start=1)}
        kw_rank = {cid: i for i, cid in enumerate(kw, start=1)}

        hits = []
        for cid, score in rrf([[c for c, _ in vec], kw])[:k]:
            r = self.rows[self.pos_of_id[cid]]
            hits.append(Hit(
                chunk_id=r["chunk_id"], doc_id=r["doc_id"], context_header=r["context_header"],
                content=r["content"], url=r["url"], source=r["source"], topic=r["topic"],
                subtopic=r["subtopic"], vector_score=vec_score.get(cid),
                vector_rank=vec_rank.get(cid), keyword_rank=kw_rank.get(cid), rrf_score=score,
            ))
        return hits

    def doc_ids(self, ids: list[int]) -> list[str]:
        return [self.rows[self.pos_of_id[i]]["doc_id"] for i in ids]
