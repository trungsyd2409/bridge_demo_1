
/**
 * Danh sách model Gemini theo thứ tự ưu tiên — gọi model đầu tiên,
 * nếu lỗi (rate limit, quota, model bị tắt...) thì tự động thử model kế tiếp.
 * Có thể override bằng biến môi trường GEMINI_MODELS (phân tách bằng dấu phẩy),
 * không cần sửa code khi muốn đổi thứ tự/thêm model mới.
 */
export const AI_MODELS: string[] = (
    process.env.GEMINI_MODELS ?? "gemini-3.6-flash"
)
    .split(",")
    .map((m) => m.trim())
    .filter(Boolean);