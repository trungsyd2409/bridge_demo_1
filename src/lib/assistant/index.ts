/**
 * Điểm vào duy nhất của trợ lý AI: askAssistant(message, profile).
 *
 *   câu hỏi tiếng Việt
 *     → NLU (intent, entities, risk, englishQuery)
 *     → Grounding song song: RAG (embed → hybrid → RRF → rerank) | bảng lương | ABN
 *     → LLM sinh câu trả lời 5 phần (hoặc mẫu dự phòng)
 *     + khối khẩn cấp tạo bằng code khi risk cao
 */
import { isFakeMode } from "./config";
import { generateAnswer, fallbackAnswer } from "./answer";
import { GeminiAuthError } from "./gemini";
import { gatherEvidence } from "./grounding";
import { analyze, cleanMessage, fallbackNlu, isSelfHarm, scanEmergency } from "./nlu";
import { contactsFor, urgentBlock } from "./support";
import type { AssistantResponse, NluResult, TraceStep, UserProfile } from "./types";

export type { AssistantResponse, UserProfile } from "./types";

const DISCLAIMER =
  "Đây là thông tin chung, không phải tư vấn pháp lý. Hãy kiểm tra lại với Fair Work Ombudsman (13 13 94) — miễn phí và có phiên dịch tiếng Việt.";

const AUTH_MESSAGE = "API key Gemini sai hoặc thiếu: đang chạy chế độ không có AI (từ khoá + câu trả lời mẫu)";

export async function askAssistant(
  rawMessage: string,
  profile: UserProfile = {},
): Promise<{ response: AssistantResponse; trace: TraceStep[] }> {
  const trace: TraceStep[] = [];
  const message = cleanMessage(rawMessage);
  let offline = false;

  // ---- NLU ----
  let t0 = performance.now();
  let nlu: NluResult;
  try {
    const result = await analyze(message);
    nlu = result.nlu;
    trace.push({ step: "NLU", ms: ms(t0), ok: !result.error, detail: { model: result.model, error: result.error, ...nlu } });
  } catch (e) {
    if (!(e instanceof GeminiAuthError)) throw e;
    offline = true;
    nlu = fallbackNlu(message, scanEmergency(message));
    trace.push({ step: "NLU", ms: ms(t0), ok: false, detail: { ...nlu, error: AUTH_MESSAGE } });
  }

  // ---- Grounding ----
  t0 = performance.now();
  const grounding = await gatherEvidence(nlu, profile, offline);
  trace.push(...grounding.trace);
  if (grounding.authError) {
    offline = true;
    trace.push({ step: "Grounding", ms: ms(t0), ok: false, detail: AUTH_MESSAGE });
  }

  // ---- Câu trả lời ----
  const contacts = contactsFor(nlu.intent, profile);
  t0 = performance.now();
  let answer;
  let mode: "llm" | "fallback" = "fallback";
  if (offline || isFakeMode()) {
    answer = fallbackAnswer(nlu, profile, grounding.evidence, contacts);
    trace.push({ step: "Sinh câu trả lời", ms: ms(t0), ok: true, detail: offline ? "mẫu (không có AI)" : "mẫu (chế độ giả)" });
  } else {
    try {
      const result = await generateAnswer(message, nlu, profile, grounding.evidence, contacts);
      answer = result.answer;
      mode = result.mode;
      trace.push({ step: "Sinh câu trả lời", ms: ms(t0), ok: result.mode === "llm", detail: { model: result.model, error: result.error, grounding: answer.grounding } });
    } catch (e) {
      if (!(e instanceof GeminiAuthError)) throw e;
      answer = fallbackAnswer(nlu, profile, grounding.evidence, contacts);
      trace.push({ step: "Sinh câu trả lời", ms: ms(t0), ok: false, detail: AUTH_MESSAGE });
    }
  }

  const response: AssistantResponse = {
    answer,
    sources: grounding.evidence.map((e, i) => ({ n: i + 1, title: e.title, source: e.source, url: e.url, kind: e.kind })),
    urgent: urgentBlock(nlu, isSelfHarm(nlu.emergencyKeywords)),
    intent: nlu.intent,
    risk: nlu.risk,
    mode,
    disclaimer: DISCLAIMER,
  };
  return { response, trace };
}

function ms(t0: number): number {
  return Math.round(performance.now() - t0);
}
