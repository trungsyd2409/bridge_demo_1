/**
 * API của trợ lý AI:  POST /api/assistant
 *
 * Không cần đăng nhập, không cần database. Route này chỉ là cây cầu giữa box chat
 * và bộ não AI trong src/lib/assistant/ — đúng hàm mà `npm run ask` đang gọi.
 *
 * Box chat gửi lên:   { message: "câu hỏi", profile: { visa, industry, employment, state } }
 * Route trả về:       { response: {...} }   (format mà giao diện hiển thị)
 *
 * Lịch sử chat do phía giao diện tự giữ (state của React / localStorage).
 * Phần AI không lưu gì cả.
 */
import { NextRequest, NextResponse } from "next/server";
import { askAssistant } from "@/lib/assistant";
import { MAX_MESSAGE_CHARS } from "@/lib/assistant/config";
import { profileFromOnboarding, toLegacyResponse } from "@/lib/assistant/legacy";
import { sanitizeProfile } from "@/lib/assistant/profile";
import { checkRateLimit } from "@/lib/rateLimit";
import type { UserProfile } from "@/lib/assistant/types";

// BẮT BUỘC: bộ não AI dùng node:sqlite và đọc file data/rag.db.
// Thiếu dòng runtime này Next.js có thể chạy route ở Edge -> chết ngay.
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
// Vercel: cho phép chạy tối đa 60 giây (gói Hobby vẫn bị cắt ở 10s).
export const maxDuration = 60;

// Chống spam theo địa chỉ IP: 15 câu hỏi trong 5 phút.
// Mỗi câu hỏi tốn 3-4 lần gọi Gemini, nên con số này bảo vệ hạn mức API của bạn.
const RATE_LIMIT = 15;
const RATE_WINDOW_MS = 5 * 60 * 1000;

/** Lấy IP người gọi. Sau reverse proxy (Vercel) thì IP thật nằm ở x-forwarded-for. */
function clientIp(req: NextRequest): string {
  const forwarded = req.headers.get("x-forwarded-for");
  if (forwarded) return forwarded.split(",")[0].trim();
  return req.headers.get("x-real-ip") ?? "unknown";
}

/**
 * Hồ sơ do trình duyệt gửi lên -> KHÔNG được tin tuyệt đối.
 * Nhận cả 2 dạng: mã ("student") và nhãn onboarding tiếng Việt ("Du học sinh (Student)").
 * Giá trị lạ bị bỏ qua (chỉ mất phần lọc, không làm hỏng câu trả lời).
 */
function readProfile(raw: unknown): UserProfile {
  if (!raw || typeof raw !== "object") return {};
  const asCode = sanitizeProfile(raw);
  const asLabel = profileFromOnboarding(raw as Record<string, unknown>);
  return {
    visa: asCode.visa ?? asLabel.visa,
    industry: asCode.industry ?? asLabel.industry,
    employment: asCode.employment ?? asLabel.employment,
    state: asCode.state,
  };
}

export async function POST(req: NextRequest) {
  // ---- 1. Chống spam ----
  const limit = checkRateLimit(`assistant:${clientIp(req)}`, RATE_LIMIT, RATE_WINDOW_MS);
  if (!limit.allowed) {
    const seconds = Math.ceil(limit.retryAfterMs / 1000);
    return NextResponse.json(
      { error: `Bạn đang hỏi hơi nhanh. Vui lòng thử lại sau ${seconds} giây.` },
      { status: 429, headers: { "Retry-After": String(seconds) } }
    );
  }

  // ---- 2. Đọc dữ liệu gửi lên ----
  let body: { message?: unknown; profile?: unknown; trace?: unknown };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Dữ liệu gửi lên không hợp lệ." }, { status: 400 });
  }

  const message = typeof body.message === "string" ? body.message.trim() : "";
  if (!message) {
    return NextResponse.json({ error: "Bạn chưa nhập câu hỏi." }, { status: 400 });
  }
  if (message.length > MAX_MESSAGE_CHARS) {
    return NextResponse.json(
      { error: `Câu hỏi quá dài (tối đa ${MAX_MESSAGE_CHARS} ký tự).` },
      { status: 400 }
    );
  }

  // ---- 3. Gọi trợ lý ----
  try {
    const profile = readProfile(body.profile);
    const { response, trace } = await askAssistant(message, profile);

    // trace chỉ trả khi client hỏi xin: dùng cho trang demo / lúc trình bày với giám khảo.
    return NextResponse.json({
      response: toLegacyResponse(response),
      ...(body.trace === true ? { trace } : {}),
    });
  } catch (err) {
    console.error("[/api/assistant] lỗi:", err);
    return NextResponse.json(
      { error: "Trợ lý đang gặp sự cố. Vui lòng thử lại sau ít phút." },
      { status: 500 }
    );
  }
}

/** Mở thẳng /api/assistant bằng trình duyệt sẽ vào đây — dùng để kiểm tra route còn sống. */
export async function GET() {
  return NextResponse.json({
    ok: true,
    hint: 'Route đang chạy. Gửi POST với body {"message":"..."} để hỏi trợ lý.',
  });
}
