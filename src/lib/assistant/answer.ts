/**
 * Sinh câu trả lời tiếng Việt 5 phần từ bằng chứng đã gom.
 * LLM chỉ được dùng thông tin trong EVIDENCE và phải trích số [n].
 * Lỗi/không có key -> mẫu trả lời dựng sẵn theo intent (vẫn hữu ích, vẫn có nguồn).
 */
import { ANSWER_MODELS, TIMEOUT } from "./config";
import { GeminiAuthError, generateJson } from "./gemini";
import type { AnswerParts, Evidence, Intent, NluResult, SupportContact, UserProfile } from "./types";
import { compareWage } from "./wages";

const SYSTEM_PROMPT = `Bạn là trợ lý của app "Bạn Đồng Hành", giúp người lao động nhập cư Việt Nam tại Úc hiểu quyền lợi nơi làm việc.

Quy tắc bắt buộc:
1. Trả lời bằng tiếng Việt đơn giản, xưng "bạn". Thuật ngữ tiếng Anh (award, payslip, casual) giữ nguyên nhưng giải thích ngắn.
2. CHỈ dùng thông tin trong phần EVIDENCE. Mọi con số (tiền, giờ, thời hạn) phải lấy từ EVIDENCE, không tự nhớ.
3. citations: số thứ tự các bằng chứng [n] mà câu trả lời dựa vào.
4. grounding: "grounded" nếu EVIDENCE trả lời trực tiếp; "partial" nếu chỉ một phần; "insufficient" nếu EVIDENCE không đủ.
   Khi "insufficient": nói rõ chưa có đủ thông tin chính thức và khuyên liên hệ cơ quan trong CONTACTS. KHÔNG đoán.
5. Không khẳng định kết luận pháp lý chắc chắn ("chắc chắn bạn thắng kiện"); nói "có thể", "thường" khi phù hợp.
6. whatToDo: 2-4 bước cụ thể, làm được ngay. evidenceToKeep: 2-4 loại giấy tờ/bằng chứng nên lưu.
   whoCanHelp: chọn từ CONTACTS, ghi tên kèm số điện thoại.
7. Nếu người dùng lo sợ về visa: nhắc rằng liên hệ Fair Work không làm visa bị huỷ (nếu EVIDENCE có nói điều này).`;

const SCHEMA = {
  type: "OBJECT",
  properties: {
    whatIsHappening: { type: "STRING" },
    whyItMatters: { type: "STRING" },
    whatToDo: { type: "ARRAY", items: { type: "STRING" } },
    evidenceToKeep: { type: "ARRAY", items: { type: "STRING" } },
    whoCanHelp: { type: "ARRAY", items: { type: "STRING" } },
    citations: { type: "ARRAY", items: { type: "INTEGER" } },
    grounding: { type: "STRING", enum: ["grounded", "partial", "insufficient"] },
  },
  required: ["whatIsHappening", "whyItMatters", "whatToDo", "evidenceToKeep", "whoCanHelp", "citations", "grounding"],
};

export function buildPrompt(
  message: string, nlu: NluResult, profile: UserProfile, evidence: Evidence[], contacts: SupportContact[],
): string {
  const ev = evidence.length
    ? evidence.map((e, i) => `[${i + 1}] (${e.source}) ${e.title}\n${e.content.slice(0, 1500)}`).join("\n\n")
    : "(không có bằng chứng nào đủ liên quan)";
  const who = contacts.map((c) => `- ${c.name}${c.phone ? ` (${c.phone})` : ""}: ${c.note}`).join("\n");
  const prof = Object.entries(profile).filter(([, v]) => v).map(([k, v]) => `${k}=${v}`).join(", ") || "không rõ";
  return `HỒ SƠ: ${prof}
PHÂN LOẠI: intent=${nlu.intent}, risk=${nlu.risk}

CÂU HỎI:
${message}

EVIDENCE:
${ev}

CONTACTS:
${who}`;
}

// ---------- kiểm tra JSON ----------

const str = (v: unknown, max = 1200) => (typeof v === "string" && v.trim() ? v.trim().slice(0, max) : null);
const strList = (v: unknown) =>
  Array.isArray(v) ? v.map((x) => str(x, 400)).filter((x): x is string => !!x).slice(0, 6) : [];

export function validateAnswer(raw: unknown, evidenceCount: number): AnswerParts | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const whatIsHappening = str(r.whatIsHappening);
  const whyItMatters = str(r.whyItMatters);
  const whatToDo = strList(r.whatToDo);
  if (!whatIsHappening || !whyItMatters || whatToDo.length === 0) return null;

  const citations = Array.isArray(r.citations)
    ? [...new Set(r.citations.filter((n): n is number => Number.isInteger(n) && n >= 1 && n <= evidenceCount))]
    : [];
  let grounding = ["grounded", "partial", "insufficient"].includes(r.grounding as string)
    ? (r.grounding as AnswerParts["grounding"])
    : "partial";
  if (evidenceCount === 0) grounding = "insufficient"; // không có bằng chứng thì không thể "grounded"
  if (grounding === "grounded" && citations.length === 0) grounding = "partial";

  return {
    whatIsHappening, whyItMatters, whatToDo,
    evidenceToKeep: strList(r.evidenceToKeep),
    whoCanHelp: strList(r.whoCanHelp),
    citations, grounding,
  };
}

// ---------- mẫu dự phòng ----------

const TEMPLATES: Record<Intent, Pick<AnswerParts, "whatIsHappening" | "whyItMatters" | "whatToDo" | "evidenceToKeep">> = {
  underpayment: {
    whatIsHappening: "Có thể bạn đang được trả thấp hơn mức lương tối thiểu hoặc mức trong award (thang lương của ngành).",
    whyItMatters: "Mọi người lao động ở Úc, dù có visa gì, đều phải được trả ít nhất mức tối thiểu. Trả tiền mặt vẫn phải đủ mức này.",
    whatToDo: ["Ghi lại ngày, giờ làm và số tiền nhận mỗi tuần.", "Kiểm tra mức lương của ngành bằng công cụ Pay Calculator của Fair Work.", "Liên hệ Fair Work Ombudsman để được tư vấn miễn phí."],
    evidenceToKeep: ["Lịch làm việc / ảnh chụp roster", "Tin nhắn với chủ về lương", "Payslip hoặc biên nhận tiền mặt"],
  },
  no_payslip: {
    whatIsHappening: "Chủ không đưa payslip (phiếu lương) cho bạn.",
    whyItMatters: "Chủ phải đưa payslip sau mỗi lần trả lương, kể cả khi trả tiền mặt. Payslip là bằng chứng quan trọng nếu bị trả thiếu.",
    whatToDo: ["Nhắn tin (có lưu lại) đề nghị chủ gửi payslip.", "Tự ghi lại giờ làm và tiền nhận mỗi tuần.", "Liên hệ Fair Work Ombudsman nếu chủ vẫn không đưa."],
    evidenceToKeep: ["Tin nhắn đề nghị gửi payslip", "Sổ ghi giờ làm của bạn", "Sao kê ngân hàng"],
  },
  unsafe: {
    whatIsHappening: "Nơi làm việc của bạn có thể không an toàn.",
    whyItMatters: "Mọi người lao động có quyền được làm việc an toàn, bất kể visa. Chủ phải cung cấp đồ bảo hộ miễn phí.",
    whatToDo: ["Nếu có nguy hiểm trước mắt, dừng việc và rời khỏi chỗ nguy hiểm.", "Báo cho chủ bằng tin nhắn (có lưu lại).", "Liên hệ cơ quan an toàn lao động của bang."],
    evidenceToKeep: ["Ảnh chụp chỗ không an toàn", "Giấy khám bệnh nếu bị thương", "Tin nhắn báo cho chủ"],
  },
  visa_threat: {
    whatIsHappening: "Bạn đang lo lắng về visa liên quan đến công việc.",
    whyItMatters: "Quyền lợi lao động không phụ thuộc visa. Chủ không có quyền huỷ visa của bạn, và chủ không được giữ hộ chiếu của bạn.",
    whatToDo: ["Kiểm tra điều kiện visa của bạn trên VEVO.", "Liên hệ Fair Work Ombudsman — việc này không làm visa bị huỷ.", "Không đưa hộ chiếu cho chủ giữ."],
    evidenceToKeep: ["Tin nhắn chủ đe doạ về visa", "Ảnh chụp điều kiện visa (VEVO)", "Lịch làm việc"],
  },
  harassment: {
    whatIsHappening: "Bạn có thể đang bị quấy rối hoặc đối xử không đúng ở nơi làm việc.",
    whyItMatters: "Quấy rối tình dục và phân biệt đối xử ở nơi làm việc là trái luật. Chủ phải có biện pháp ngăn chặn.",
    whatToDo: ["Ghi lại sự việc: ngày, giờ, lời nói, người chứng kiến.", "Nói với người tin cậy.", "Liên hệ Australian Human Rights Commission."],
    evidenceToKeep: ["Tin nhắn, email", "Ghi chép sự việc", "Tên người chứng kiến"],
  },
  unfair_dismissal: {
    whatIsHappening: "Bạn có thể đã bị cho nghỉ việc không đúng.",
    whyItMatters: "Nếu cho rằng mình bị đuổi việc không công bằng, thời hạn nộp đơn lên Fair Work Commission rất ngắn.",
    whatToDo: ["Liên hệ Fair Work Commission NGAY để biết thời hạn.", "Yêu cầu chủ nói rõ lý do bằng văn bản.", "Kiểm tra bạn đã nhận đủ lương và tiền báo trước chưa."],
    evidenceToKeep: ["Tin nhắn/email báo nghỉ việc", "Payslip gần nhất", "Hợp đồng lao động"],
  },
  contract_hours: {
    whatIsHappening: "Bạn có thắc mắc về hợp đồng, giờ làm hoặc hình thức làm việc (ví dụ bị yêu cầu làm ABN).",
    whyItMatters: "Bị ép làm contractor dùng ABN trong khi thực chất là nhân viên có thể là sham contracting — trái luật.",
    whatToDo: ["Đọc kỹ giấy tờ trước khi ký.", "Ghi lại giờ làm, ai phân công việc, ai cung cấp dụng cụ.", "Hỏi Fair Work Ombudsman về hình thức làm việc của bạn."],
    evidenceToKeep: ["Hợp đồng hoặc thư mời làm việc", "Roster / lịch làm", "Tin nhắn về ABN"],
  },
  general: {
    whatIsHappening: "Mình chưa xác định rõ vấn đề của bạn.",
    whyItMatters: "Mọi người lao động ở Úc đều có quyền lợi cơ bản như nhau, dù có visa gì.",
    whatToDo: ["Mô tả thêm: bạn làm ngành gì, vấn đề là lương, giờ làm, an toàn hay visa?", "Liên hệ Fair Work Ombudsman nếu cần tư vấn ngay."],
    evidenceToKeep: ["Lịch làm việc", "Tin nhắn với chủ", "Payslip"],
  },
};

export function fallbackAnswer(nlu: NluResult, profile: UserProfile, evidence: Evidence[], contacts: SupportContact[]): AnswerParts {
  const t = TEMPLATES[nlu.intent];
  let whatIsHappening = t.whatIsHappening;
  const rate = nlu.entities.hourlyRate;
  if (rate !== undefined && nlu.intent === "underpayment") {
    const cmp = compareWage(rate, profile.employment === "casual");
    whatIsHappening = cmp.shortfallPerHour > 0
      ? `Bạn nói được trả $${rate.toFixed(2)}/giờ — thấp hơn mức tối thiểu ${cmp.isCasual ? "cho casual " : ""}$${cmp.minimum.toFixed(2)}/giờ khoảng $${cmp.shortfallPerHour.toFixed(2)} mỗi giờ.`
      : `Bạn nói được trả $${rate.toFixed(2)}/giờ, không thấp hơn mức tối thiểu quốc gia $${cmp.minimum.toFixed(2)}/giờ — nhưng award của ngành bạn có thể cao hơn.`;
  }
  return {
    ...t,
    whatIsHappening,
    whoCanHelp: contacts.map((c) => `${c.name}${c.phone ? ` — ${c.phone}` : ""}`),
    citations: evidence.slice(0, 3).map((_, i) => i + 1),
    grounding: evidence.length ? "partial" : "insufficient",
  };
}

export async function generateAnswer(
  message: string, nlu: NluResult, profile: UserProfile, evidence: Evidence[], contacts: SupportContact[],
): Promise<{ answer: AnswerParts; mode: "llm" | "fallback"; model?: string; error?: string }> {
  try {
    const { data, model } = await generateJson<unknown>({
      models: ANSWER_MODELS,
      system: SYSTEM_PROMPT,
      prompt: buildPrompt(message, nlu, profile, evidence, contacts),
      schema: SCHEMA,
      timeoutMs: TIMEOUT.answer,
      temperature: 0.2,
    });
    const answer = validateAnswer(data, evidence.length);
    if (answer) return { answer, mode: "llm", model };
    return { answer: fallbackAnswer(nlu, profile, evidence, contacts), mode: "fallback", error: "JSON câu trả lời không hợp lệ" };
  } catch (e) {
    if (e instanceof GeminiAuthError) throw e;
    return { answer: fallbackAnswer(nlu, profile, evidence, contacts), mode: "fallback", error: (e as Error).message };
  }
}
