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
// Rồi ghi đè trong .env.local, ví dụ:   AI_NLU_MODELS=gemini-3.5-flash-lite
function modelList(envName: string, fallback: string): string[] {
  return (process.env[envName] ?? fallback).split(",").map((m) => m.trim()).filter(Boolean);
}

// BA TẦNG — trước đây cả ba bước dùng chung một danh sách flash-lite, nghĩa là bước
// viết câu trả lời (bước cần suy luận nhất) cũng chạy trên model yếu nhất.
//   FLASH  — thông minh hơn, đắt hơn. Dùng cho bước cần suy luận.
//   LITE   — rẻ, nhanh; làm dự phòng khi FLASH lỗi hoặc hết quota.
//   ALIAS  — "…-latest" là bí danh Google tự trỏ sang bản mới. Để CUỐI cùng làm phao cứu
//            sinh: nếu để đầu thì model đổi ngầm, kết quả `npm run ask:eval` hết lặp lại được.
const FLASH_MODELS = "gemini-3.8-flash,gemini-3.7-flash,gemini-3.6-flash";
const LITE_MODELS = "gemini-3.5-flash-lite,gemini-3.1-flash-lite";
const ALIAS_MODELS = "gemini-flash-latest,gemini-flash-lite-latest";

// GEMINI_MODELS: biến cũ, nếu đã đặt thì nó thay cho cả ba tầng (giữ để không vỡ deploy cũ).
const OVERRIDE_ALL = process.env.GEMINI_MODELS?.trim();
const chain = (head: string) => OVERRIDE_ALL || `${head},${LITE_MODELS},${ALIAS_MODELS}`;

// Hiểu câu hỏi tiếng Việt (kể cả gõ không dấu, lẫn tiếng Anh) — flash-lite hay phân loại sai.
export const NLU_MODELS = modelList("AI_NLU_MODELS", chain(FLASH_MODELS));
// Chấm điểm 12 đoạn văn: prompt dài nhất, tốn nhất. Muốn tiết kiệm thì đặt
// AI_RERANK_MODELS=gemini-3.5-flash-lite trong .env.local rồi đo lại bằng npm run ask:eval.
export const RERANK_MODELS = modelList("AI_RERANK_MODELS", chain(FLASH_MODELS));
// Viết câu trả lời cuối: bước quan trọng nhất, luôn ưu tiên model mạnh nhất.
export const ANSWER_MODELS = modelList("AI_ANSWER_MODELS", chain(FLASH_MODELS));

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

/** AI_SKIP_RERANK=1: bỏ bước rerank để trả lời nhanh hơn (đổi lại kém chính xác hơn). */
export function isRerankOff(): boolean {
  return process.env.AI_SKIP_RERANK === "1";
}