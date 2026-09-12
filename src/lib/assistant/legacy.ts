/**
 * Cầu nối giữa pipeline RAG mới và phần app có sẵn:
 *   1. profileFromOnboarding(): nhãn tiếng Việt lưu trong bảng profiles -> mã của taxonomy
 *   2. toLegacyResponse(): AssistantResponse mới -> định dạng mà trang /assistant cũ hiển thị
 *
 * Nhờ vậy trang /assistant, lịch sử chat và bảng ai_messages không phải sửa cấu trúc.
 */
import type { AssistantResponse as LegacyResponse } from "@/lib/assistantShared";
import type { AssistantResponse, Intent, UserProfile } from "./types";

// Onboarding lưu NHÃN (vd "Du học sinh (Student)"), không lưu mã.
// So khớp theo từ khoá không phân biệt hoa thường; nhãn "Không chắc chắn"/"Khác" -> không lọc.
const VISA_RULES: [RegExp, NonNullable<UserProfile["visa"]>][] = [
  [/student|du học/i, "student"],
  [/working holiday|whv/i, "whv"],
  [/temporary work|temp_work|lao động/i, "temp_work"],
  [/permanent|thường trú|\bpr\b/i, "pr"],
];
const INDUSTRY_RULES: [RegExp, NonNullable<UserProfile["industry"]>][] = [
  [/nhà hàng|cà phê|quán|hospitality/i, "hospitality"],
  [/nail|làm đẹp|beauty/i, "beauty"],
  [/dọn dẹp|cleaning/i, "cleaning"],
  [/bán lẻ|retail/i, "retail"],
  [/nông trại|farm/i, "farm"],
];
const EMPLOYMENT_RULES: [RegExp, NonNullable<UserProfile["employment"]>][] = [
  [/casual|thời vụ/i, "casual"],
  [/part[-_ ]?time|bán thời gian/i, "part_time"],
  [/full[-_ ]?time|toàn thời gian/i, "full_time"],
  [/contractor|abn/i, "contractor"],
];

function match<T>(value: unknown, rules: [RegExp, T][]): T | undefined {
  if (typeof value !== "string" || !value.trim()) return undefined;
  return rules.find(([re]) => re.test(value))?.[1];
}

export function profileFromOnboarding(row: Record<string, unknown> | undefined | null): UserProfile {
  if (!row) return {};
  return {
    visa: match(row.visa, VISA_RULES),
    industry: match(row.industry, INDUSTRY_RULES),
    employment: match(row.employment, EMPLOYMENT_RULES),
  };
}

// Tên chủ đề hiển thị, cùng giọng với các kịch bản cũ trong aiAssistant.ts
export const TOPIC_LABEL: Record<Intent, string> = {
  underpayment: "Nghi ngờ bị trả lương thấp hơn quy định",
  no_payslip: "Không nhận được phiếu lương (payslip)",
  unsafe: "Điều kiện làm việc không an toàn",
  visa_threat: "Vấn đề liên quan đến visa",
  harassment: "Quấy rối hoặc phân biệt đối xử tại nơi làm việc",
  unfair_dismissal: "Bị cho nghỉ việc / sa thải",
  contract_hours: "Hợp đồng, giờ làm hoặc hình thức làm việc",
  general: "Câu hỏi chung về quyền lợi tại nơi làm việc",
};

export function toLegacyResponse(r: AssistantResponse): LegacyResponse {
  return {
    topic: TOPIC_LABEL[r.intent],
    whatMightBeHappening: r.answer.whatIsHappening,
    whyItMatters: r.answer.whyItMatters,
    whatYouCanDo: r.answer.whatToDo,
    evidenceToKeep: r.answer.evidenceToKeep,
    helpTags: [r.intent],
    // Các trường mới (tuỳ chọn): trang /assistant hiển thị nếu có
    whoCanHelp: r.answer.whoCanHelp,
    sources: r.sources.map((s) => ({ ...s, cited: r.answer.citations.includes(s.n) })),
    urgent: r.urgent.show ? { message: r.urgent.message, contacts: r.urgent.contacts } : undefined,
    grounding: r.answer.grounding,
    engine: r.mode === "llm" ? "rag-gemini" : "rag-fallback",
  };
}
