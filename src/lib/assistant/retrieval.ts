/**
 * Tìm kiếm trong rag.db — bản TypeScript của lib/search.py bên pipeline.
 * Test test/retrieval.test.ts so kết quả với Python để đảm bảo hai bên giống nhau.
 *
 *   englishQuery ──► vectorSearch (cosine) ──┐
 *               └──► keywordSearch (BM25)  ──┴─► rrf() ──► ứng viên cho rerank
 */
import { DatabaseSync } from "node:sqlite";
import { EMBED_DIM, RAG_DB_PATH, RRF_K, isFakeMode } from "./config";
import type { SearchHit } from "./types";

export interface Filters {
  topics?: string[];
  languages?: string[];
  industry?: string; // một giá trị từ hồ sơ; chunk khớp nếu chứa giá trị này hoặc "all"
  visa?: string;
  employment?: string;
}

interface Row {
  id: number;
  chunkId: string;
  docId: string;
  contextHeader: string;
  content: string;
  url: string;
  source: string;
  language: string;
  topic: string;
  subtopic: string;
  industry: string[];
  visa: string[];
  employment: string[];
}

// ---------- Hàm thuần (không đụng database) ----------

/** Reciprocal Rank Fusion: điểm = tổng 1 / (k + hạng), hạng bắt đầu từ 1. */
export function rrf<T>(rankedLists: T[][], k = RRF_K): [T, number][] {
  const scores = new Map<T, number>();
  for (const list of rankedLists) {
    list.forEach((item, i) => scores.set(item, (scores.get(item) ?? 0) + 1 / (k + i + 1)));
  }
  return [...scores.entries()].sort((a, b) => b[1] - a[1]);
}

const WORD = /[a-zA-ZÀ-ỹ0-9]+/g;
const STOPWORDS = new Set([
  "a", "an", "the", "is", "are", "am", "was", "were", "be", "been", "do", "does", "did",
  "i", "me", "my", "you", "your", "he", "she", "it", "we", "they", "them", "their",
  "to", "of", "in", "on", "at", "for", "with", "and", "or", "but", "if", "so", "not",
  "can", "could", "should", "would", "will", "what", "when", "where", "who", "how", "why",
  "this", "that", "these", "those", "there", "have", "has", "had", "about", "from", "by",
]);

/** Câu hỏi -> truy vấn FTS5 an toàn: từ khoá trong ngoặc kép, nối bằng OR. */
export function buildFtsQuery(text: string): string {
  const seen = new Set<string>();
  const words: string[] = [];
  for (const w of text.toLowerCase().match(WORD) ?? []) {
    if (w.length < 2 || STOPWORDS.has(w) || seen.has(w)) continue;
    seen.add(w);
    words.push(`"${w}"`);
  }
  return words.join(" OR ");
}

// ---------- Chỉ mục ----------

export class RagIndex {
  readonly meta: Record<string, string>;
  readonly rows: Row[];
  private readonly db: DatabaseSync;
  private readonly matrix: Float32Array; // rows.length × 768, liền một khối
  private readonly posOfId = new Map<number, number>();

  constructor(dbPath = RAG_DB_PATH) {
    this.db = new DatabaseSync(dbPath, { readOnly: true });
    const metaRows = this.db.prepare("SELECT key, value FROM meta").all() as { key: string; value: string }[];
    this.meta = Object.fromEntries(metaRows.map((r) => [r.key, r.value]));
    if (this.meta.embed_dim !== String(EMBED_DIM)) {
      throw new Error(`rag.db có vector ${this.meta.embed_dim} chiều, app cần ${EMBED_DIM}`);
    }

    const raw = this.db
      .prepare(
        "SELECT id, chunk_id, doc_id, context_header, content, url, source, language, topic, subtopic, " +
          "industry, visa, employment, embedding FROM rag_chunks ORDER BY id",
      )
      .all() as Record<string, unknown>[];

    this.matrix = new Float32Array(raw.length * EMBED_DIM);
    this.rows = raw.map((r, i) => {
      const blob = r.embedding as Uint8Array;
      // BLOB float32 little-endian -> Float32Array (giống MemoryMarshal.Cast<byte, float> trong C#)
      this.matrix.set(new Float32Array(blob.buffer, blob.byteOffset, blob.byteLength / 4), i * EMBED_DIM);
      this.posOfId.set(r.id as number, i);
      return {
        id: r.id as number,
        chunkId: r.chunk_id as string,
        docId: r.doc_id as string,
        contextHeader: r.context_header as string,
        content: r.content as string,
        url: r.url as string,
        source: r.source as string,
        language: r.language as string,
        topic: r.topic as string,
        subtopic: r.subtopic as string,
        industry: JSON.parse(r.industry as string),
        visa: JSON.parse(r.visa as string),
        employment: JSON.parse(r.employment as string),
      };
    });
  }

  get isFakeVectors(): boolean {
    return (this.meta.embed_model ?? "").startsWith("fake");
  }

  close(): void {
    this.db.close();
  }

  private matches(r: Row, f?: Filters): boolean {
    if (!f) return true;
    if (f.topics?.length && !f.topics.includes(r.topic)) return false;
    if (f.languages?.length && !f.languages.includes(r.language)) return false;
    for (const key of ["industry", "visa", "employment"] as const) {
      const wanted = f[key];
      if (wanted && !r[key].includes("all") && !r[key].includes(wanted)) return false;
    }
    return true;
  }

  /** [id, cosine] giảm dần. Vector đã chuẩn hoá nên cosine = tích vô hướng. */
  vectorSearch(query: Float32Array, k: number, f?: Filters): [number, number][] {
    if (query.length !== EMBED_DIM) throw new Error(`vector câu hỏi ${query.length} chiều, cần ${EMBED_DIM}`);
    const scored: [number, number][] = [];
    this.rows.forEach((r, i) => {
      if (!this.matches(r, f)) return;
      let dot = 0;
      const offset = i * EMBED_DIM;
      for (let d = 0; d < EMBED_DIM; d++) dot += this.matrix[offset + d] * query[d];
      scored.push([r.id, dot]);
    });
    return scored.sort((a, b) => b[1] - a[1]).slice(0, k);
  }

  /** [id] theo BM25. bm25() của SQLite: điểm càng ÂM càng liên quan; heading nặng gấp đôi nội dung. */
  keywordSearch(query: string, k: number, f?: Filters): number[] {
    const fts = buildFtsQuery(query);
    if (!fts) return [];
    const rows = this.db
      .prepare("SELECT rowid FROM rag_fts WHERE rag_fts MATCH ? ORDER BY bm25(rag_fts, 2.0, 1.0) LIMIT ?")
      .all(fts, k * 5) as { rowid: number }[];
    return rows
      .map((r) => r.rowid)
      .filter((id) => this.matches(this.rows[this.posOfId.get(id)!], f))
      .slice(0, k);
  }

  /**
   * Hybrid = RRF của hai nhánh.
   * boostTopic: thêm nhánh thứ ba chỉ gồm chunk thuộc topic của NLU. Đây là lọc "mềm":
   * NLU đoán sai topic thì chunk đúng vẫn có cơ hội từ hai nhánh chính.
   */
  hybridSearch(
    queryVec: Float32Array,
    queryText: string,
    k: number,
    f?: Filters,
    candidates = 20,
    boostTopic?: string,
  ): SearchHit[] {
    const vec = this.vectorSearch(queryVec, candidates, f);
    const kw = this.keywordSearch(queryText, candidates, f);
    const lists = [vec.map(([id]) => id), kw];
    if (boostTopic) {
      const topicOnly = this.vectorSearch(queryVec, candidates, { ...f, topics: [boostTopic] });
      lists.push(topicOnly.map(([id]) => id));
    }
    const vecScore = new Map(vec);
    const vecRank = new Map(vec.map(([id], i) => [id, i + 1]));
    const kwRank = new Map(kw.map((id, i) => [id, i + 1]));

    return rrf(lists)
      .slice(0, k)
      .map(([id, score]) => {
        const r = this.rows[this.posOfId.get(id)!];
        return {
          id,
          chunkId: r.chunkId,
          docId: r.docId,
          contextHeader: r.contextHeader,
          content: r.content,
          url: r.url,
          source: r.source,
          topic: r.topic,
          subtopic: r.subtopic,
          vectorScore: vecScore.get(id),
          vectorRank: vecRank.get(id),
          keywordRank: kwRank.get(id),
          rrfScore: score,
        };
      });
  }

  /** Chỉ BM25, dùng khi không embed được câu hỏi (mạng lỗi, timeout). */
  keywordOnlySearch(queryText: string, k: number, f?: Filters): SearchHit[] {
    return this.keywordSearch(queryText, k, f).map((id, i) => {
      const r = this.rows[this.posOfId.get(id)!];
      return {
        id, chunkId: r.chunkId, docId: r.docId, contextHeader: r.contextHeader, content: r.content,
        url: r.url, source: r.source, topic: r.topic, subtopic: r.subtopic,
        keywordRank: i + 1, rrfScore: 1 / (RRF_K + i + 1),
      };
    });
  }

  chunkIds(ids: number[]): string[] {
    return ids.map((id) => this.rows[this.posOfId.get(id)!].chunkId);
  }
}

// ---------- Mở một lần, dùng lại cho mọi request ----------

// Lưu trên globalThis để khi "npm run dev" hot-reload không mở lại file liên tục
const globalCache = globalThis as unknown as { __ragIndex?: RagIndex };

export function getRagIndex(): RagIndex {
  if (!globalCache.__ragIndex) {
    const index = new RagIndex();
    if (index.isFakeVectors && !isFakeMode()) {
      index.close();
      throw new Error(
        "rag.db đang dùng vector GIẢ nhưng app chạy với Gemini thật: kết quả sẽ vô nghĩa. " +
          "Build lại rag.db với Gemini thật, hoặc đặt RAG_FAKE_GEMINI=1.",
      );
    }
    globalCache.__ragIndex = index;
  }
  return globalCache.__ragIndex;
}

/** Dùng trong test để mở file khác. */
export function resetRagIndex(): void {
  globalCache.__ragIndex?.close();
  globalCache.__ragIndex = undefined;
}
