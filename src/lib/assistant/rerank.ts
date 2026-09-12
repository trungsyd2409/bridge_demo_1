/**
 * Rerank: Gemini Flash-Lite đọc câu hỏi và từng chunk CÙNG LÚC rồi chấm 0-10.
 * RRF tìm nhanh nhưng chưa hiểu sắc thái; rerank loại chunk "cùng chủ đề nhưng không trả lời
 * đúng câu hỏi" (ví dụ hỏi lương casual mà chunk nói về lương full-time).
 *
 * Kết quả rỗng là tín hiệu quan trọng: không đủ bằng chứng -> LLM phải nói "không đủ thông tin".
 */
import { FINAL_CHUNKS, RERANK_MIN_SCORE, RERANK_MODELS, TIMEOUT, isFakeMode } from "./config";
import { GeminiAuthError, generateJson } from "./gemini";
import type { SearchHit } from "./types";

const SYSTEM_PROMPT = `You score how useful each passage is for answering a worker's question
about Australian workplace rights. 0 = irrelevant, 5 = related but only partly answers,
10 = directly answers. Be strict: same topic is not enough. Return JSON only.`;

const SCHEMA = {
  type: "ARRAY",
  items: {
    type: "OBJECT",
    properties: { index: { type: "INTEGER" }, score: { type: "NUMBER" } },
    required: ["index", "score"],
  },
};

export interface RerankResult {
  hits: SearchHit[];
  mode: "gemini" | "rrf-only";
  error?: string;
}

function rrfOnly(candidates: SearchHit[], error?: string): RerankResult {
  return { hits: candidates.slice(0, FINAL_CHUNKS), mode: "rrf-only", error };
}

export function applyScores(candidates: SearchHit[], scores: { index: number; score: number }[]): SearchHit[] {
  const best = new Map<number, number>();
  for (const s of scores) {
    if (!Number.isInteger(s.index) || s.index < 0 || s.index >= candidates.length) continue;
    if (typeof s.score !== "number" || !Number.isFinite(s.score)) continue;
    best.set(s.index, Math.max(best.get(s.index) ?? -1, s.score));
  }
  return [...best.entries()]
    .filter(([, score]) => score >= RERANK_MIN_SCORE)
    .sort((a, b) => b[1] - a[1])
    .slice(0, FINAL_CHUNKS)
    .map(([i, score]) => ({ ...candidates[i], rerankScore: score }));
}

export async function rerank(englishQuery: string, candidates: SearchHit[]): Promise<RerankResult> {
  if (candidates.length === 0) return { hits: [], mode: "rrf-only" };
  if (isFakeMode()) return rrfOnly(candidates);

  const passages = candidates
    .map((c, i) => `[${i}] ${c.contextHeader}\n${c.content.slice(0, 900)}`)
    .join("\n\n");
  try {
    const { data } = await generateJson<{ index: number; score: number }[]>({
      models: RERANK_MODELS,
      system: SYSTEM_PROMPT,
      prompt: `Question: ${englishQuery}\n\nPassages:\n${passages}`,
      schema: SCHEMA,
      timeoutMs: TIMEOUT.rerank,
    });
    if (!Array.isArray(data)) return rrfOnly(candidates, "rerank trả về không phải mảng");
    return { hits: applyScores(candidates, data), mode: "gemini" };
  } catch (e) {
    if (e instanceof GeminiAuthError) throw e;
    // Rerank chỉ là bước tinh chỉnh: lỗi thì vẫn dùng thứ tự RRF, app không dừng
    return rrfOnly(candidates, (e as Error).message);
  }
}
