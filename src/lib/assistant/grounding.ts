/**
 * Grounding: gom bằng chứng từ 3 nguồn CÙNG LÚC (Promise.allSettled), rồi gộp theo priority.
 *   priority 1: API trực tiếp (ABN Lookup)
 *   priority 2: tra bảng (lương tối thiểu)
 *   priority 3: RAG (rag.db -> hybrid search -> rerank)
 * Một nguồn lỗi/chậm không làm hỏng các nguồn khác.
 */
import { FINAL_CHUNKS, RERANK_INPUT, SEARCH_CANDIDATES, TIMEOUT } from "./config";
import { GeminiAuthError, embedQuery } from "./gemini";
import { abnEvidence } from "./abn";
import { rerank } from "./rerank";
import { getRagIndex, type Filters } from "./retrieval";
import type { Evidence, NluResult, SearchHit, TraceStep, UserProfile } from "./types";
import { wageEvidence } from "./wages";

export interface GroundingResult {
  evidence: Evidence[];
  hits: SearchHit[];
  trace: TraceStep[];
  authError?: boolean;
}

export function profileFilters(profile: UserProfile): Filters {
  return { visa: profile.visa, industry: profile.industry, employment: profile.employment };
}

function hitToEvidence(h: SearchHit): Evidence {
  return {
    kind: "rag",
    priority: 3,
    title: h.contextHeader,
    content: h.content,
    source: h.source,
    url: h.url,
    score: h.rerankScore,
    chunkId: h.chunkId,
  };
}

async function timed<T>(step: string, trace: TraceStep[], fn: () => Promise<T>, detail?: (r: T) => unknown) {
  const t0 = performance.now();
  try {
    const result = await fn();
    trace.push({ step, ms: Math.round(performance.now() - t0), ok: true, detail: detail?.(result) });
    return result;
  } catch (e) {
    trace.push({ step, ms: Math.round(performance.now() - t0), ok: false, detail: (e as Error).message });
    throw e;
  }
}

async function ragBranch(nlu: NluResult, profile: UserProfile, trace: TraceStep[], offline: boolean) {
  const index = getRagIndex();
  const filters = profileFilters(profile);
  const boost = nlu.intent !== "general" ? nlu.intent : undefined;

  if (offline) {
    // Không dùng được Gemini (sai key): chỉ còn BM25, không rerank
    return timed("chỉ tìm từ khoá (không có AI)", trace, async () =>
      index.keywordOnlySearch(nlu.englishQuery, FINAL_CHUNKS, filters),
    );
  }

  let candidates: SearchHit[];
  try {
    const qvec = await timed("embed câu hỏi", trace, () => embedQuery(nlu.englishQuery, TIMEOUT.embed));
    candidates = await timed(
      "hybrid search + RRF",
      trace,
      async () => index.hybridSearch(qvec, nlu.englishQuery, RERANK_INPUT, filters, SEARCH_CANDIDATES, boost),
      (hits) => hits.map((h) => ({ chunk: h.contextHeader, vec: h.vectorRank, bm25: h.keywordRank, rrf: +h.rrfScore.toFixed(4) })),
    );
  } catch (e) {
    if (e instanceof GeminiAuthError) throw e;
    // Embedding lỗi (mạng, timeout): vẫn còn BM25, không bỏ trống bằng chứng
    candidates = await timed("chỉ tìm từ khoá (dự phòng)", trace, async () =>
      index.keywordOnlySearch(nlu.englishQuery, RERANK_INPUT, filters),
    );
  }

  const reranked = await timed("rerank", trace, () => rerank(nlu.englishQuery, candidates), (r) => ({
    mode: r.mode,
    kept: r.hits.map((h) => ({ chunk: h.contextHeader, score: h.rerankScore })),
    error: r.error,
  }));
  return reranked.hits;
}

export async function gatherEvidence(
  nlu: NluResult, profile: UserProfile, offline = false,
): Promise<GroundingResult> {
  const trace: TraceStep[] = [];
  const [rag, abn] = await Promise.allSettled([
    ragBranch(nlu, profile, trace, offline),
    timed("ABN Lookup", trace, () => abnEvidence(nlu.entities.abn), (e) => (e ? e.content : "bỏ qua (không có ABN hoặc GUID)")),
  ]);
  const wage = wageEvidence(nlu, profile.employment); // tra bảng: đồng bộ, không thể lỗi mạng

  const evidence: Evidence[] = [];
  if (abn.status === "fulfilled" && abn.value) evidence.push(abn.value);
  if (wage) evidence.push(wage);
  const hits = rag.status === "fulfilled" ? rag.value : [];
  evidence.push(...hits.map(hitToEvidence));
  evidence.sort((a, b) => a.priority - b.priority);

  const authError = rag.status === "rejected" && rag.reason instanceof GeminiAuthError;
  if (rag.status === "rejected" && !authError) {
    trace.push({ step: "RAG", ms: 0, ok: false, detail: String((rag.reason as Error)?.message ?? rag.reason) });
  }
  return { evidence, hits, trace, authError };
}
