/**
 * Cấu hình của trợ lý AI. Mọi hằng số nằm ở đây (giống config/settings.py bên pipeline).
 * Chỉ dùng phía server: file này đọc biến môi trường chứa API key.
 */
import path from "node:path";

// ---- Model ----
// Mỗi bước có một DANH SÁCH model, thử lần lượt: model đầu lỗi (vd 404 "no longer available
// to new users") thì tự chuyển sang model sau. Google khoá model cũ với project mới rất nhanh,
// nên đặt model mới nhất trước và giữ vài lựa chọn dự phòng.
//
// Xem model nào key của bạn dùng được:  npm run ask -- --models
// Rồi ghi đè trong .env.local, ví dụ:   AI_NLU_MODELS=gemini-3.1-flash-lite
function modelList(envName: string, fallback: string): string[] {
  return (process.env[envName] ?? fallback).split(",").map((m) => m.trim()).filter(Boolean);
}

const LITE_MODELS = "gemini-3.1-flash-lite,gemini-3.5-flash-lite,gemini-3.5-flash,gemini-3.7-flash,gemini-3.6-flash";
const FLASH_MODELS = "gemini-3.1-flash-lite,gemini-3.5-flash-lite,gemini-3.5-flash,gemini-3.7-flash,gemini-3.6-flash";

export const NLU_MODELS = modelList("AI_NLU_MODELS", LITE_MODELS);
export const RERANK_MODELS = modelList("AI_RERANK_MODELS", LITE_MODELS);
export const ANSWER_MODELS = modelList("AI_ANSWER_MODELS", `${FLASH_MODELS},${LITE_MODELS}`);

// ---- Embedding: PHẢI khớp với pipeline (config/settings.py) ----
export const EMBED_MODEL = "gemini-embedding-001";
export const EMBED_DIM = 768;

// ---- rag.db ----
export const RAG_DB_PATH = process.env.RAG_DB_PATH ?? path.join(process.cwd(), "data", "rag.db");

// ---- Tìm kiếm ----
export const RRF_K = 60;
export const SEARCH_CANDIDATES = 20; // mỗi nhánh (vector, BM25) lấy bao nhiêu ứng viên
export const RERANK_INPUT = 12; // số chunk đưa vào rerank
export const RERANK_MIN_SCORE = 5; // điểm 0-10; dưới ngưỡng thì bỏ
export const FINAL_CHUNKS = 4; // số chunk cuối cùng đưa cho LLM

// ---- Giới hạn thời gian (ms) ----
export const TIMEOUT = {
  nlu: 8_000,
  embed: 6_000,
  rerank: 8_000,
  answer: 25_000,
  abn: 5_000,
};

export const MAX_MESSAGE_CHARS = 2_000;

/** RAG_FAKE_GEMINI=1: chạy toàn bộ không gọi Gemini (khớp chế độ giả của pipeline). */
export function isFakeMode(): boolean {
  return process.env.RAG_FAKE_GEMINI === "1";
}
