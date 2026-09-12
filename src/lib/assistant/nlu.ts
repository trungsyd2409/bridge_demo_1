/**
 * NLU: phân tích câu hỏi tiếng Việt thành NluResult.
 *
 *   1. Làm sạch văn bản (Unicode NFC, cắt độ dài)
 *   2. Quét từ khoá khẩn cấp (không cần AI, không cần mạng)
 *   3. Gọi Gemini Flash-Lite với responseSchema: intent, entities, risk, englishQuery
 *   4. Kiểm tra JSON trả về; lỗi thì dùng fallback từ khoá
 *   5. Hợp nhất: risk lấy mức CAO HƠN giữa AI và từ khoá
 */
import { MAX_MESSAGE_CHARS, NLU_MODELS, TIMEOUT, isFakeMode } from "./config";
import { GeminiAuthError, generateJson } from "./gemini";
import { INTENTS, RISK_LEVELS, type Intent, type NluEntities, type NluResult, type RiskLevel } from "./types";

// ---------- Bước 1 ----------

export function cleanMessage(raw: string): string {
  return raw.normalize("NFC").replace(/\s+/g, " ").trim().slice(0, MAX_MESSAGE_CHARS);
}

/** Bỏ dấu tiếng Việt để so khớp cả chữ gõ không dấu: "hộ chiếu" -> "ho chieu". */
export function foldVietnamese(text: string): string {
  return text
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/đ/g, "d");
}

function containsAny(folded: string, keywords: string[]): string[] {
  return keywords.filter((k) => new RegExp(`(^|[^a-z0-9])${k}([^a-z0-9]|$)`).test(folded));
}

// ---------- Bước 2 ----------

// Viết KHÔNG DẤU: văn bản được bỏ dấu trước khi so.
const EMERGENCY_KEYWORDS = [
  "ho chieu", "giu passport", "passport", // bị giữ hộ chiếu
  "de doa", "doa giet", "doa bao", // đe doạ
  "bi danh", "danh em", "danh toi", "danh minh", "hanh hung", // bạo lực
  "bi thuong", "chay mau", "tai nan", "gay tay", "gay chan", // chấn thương
  "bi ep", "ep lam", "khong cho ve", "nhot", "khong tra giay to", // cưỡng ép
  "sam so", "hiep dam", "cuong hiep", "so mo nguoi", // tấn công tình dục
  "tu tu", "muon chet", "tu sat", // nguy cơ tự hại
];
const SELF_HARM_KEYWORDS = ["tu tu", "muon chet", "tu sat"];

export function scanEmergency(message: string): string[] {
  return containsAny(foldVietnamese(message), EMERGENCY_KEYWORDS);
}

export function isSelfHarm(keywords: string[]): boolean {
  return keywords.some((k) => SELF_HARM_KEYWORDS.includes(k));
}

// ---------- Fallback: phân loại bằng từ khoá ----------

const INTENT_KEYWORDS: Record<Exclude<Intent, "general">, string[]> = {
  no_payslip: ["payslip", "pay slip", "phieu luong", "bang luong", "giay luong"],
  underpayment: ["luong", "tien cong", "tra thieu", "tra it", "tien mat", "cash", "lam thu", "thu viec",
    "tru luong", "tru tien", "chu nhat", "ngay le", "tang ca", "wage", "tien gio", "mot gio"],
  visa_threat: ["visa", "thi thuc", "ho chieu", "huy visa", "du hoc", "sinh vien", "working holiday"],
  unsafe: ["an toan", "bi thuong", "tai nan", "hoa chat", "do bao ho", "gang tay", "khau trang", "nguy hiem"],
  harassment: ["quay roi", "sam so", "tuc tiu", "phan biet", "bat nat", "chui", "xuc pham"],
  unfair_dismissal: ["duoi viec", "sa thai", "cho nghi", "nghi viec", "bi duoi", "fired"],
  contract_hours: ["hop dong", "abn", "contractor", "gio lam", "ca lam", "lich lam", "nghi phep", "nghi om"],
};

// Câu tìm kiếm tiếng Anh theo intent: dùng khi không có bản dịch của Gemini
const INTENT_QUERY: Record<Intent, string> = {
  underpayment: "underpayment minimum wage award pay rates",
  no_payslip: "pay slips record keeping employer must provide",
  unsafe: "work health and safety rights protective equipment injury",
  visa_threat: "visa holders workplace rights visa protection",
  harassment: "sexual harassment discrimination at work complaint",
  unfair_dismissal: "unfair dismissal notice time limit",
  contract_hours: "employment contract hours sham contracting ABN",
  general: "workplace rights help",
};

// Từ quá chung chung (xuất hiện trong nhiều loại câu hỏi) chỉ tính nửa điểm,
// để "bắt làm ABN thay vì trả lương" nghiêng về contract_hours chứ không phải underpayment.
const GENERIC_KEYWORDS = new Set(["luong", "tien cong", "gio lam"]);

export function keywordIntent(message: string): Intent {
  const folded = foldVietnamese(message);
  let best: Intent = "general";
  let bestScore = 0;
  // Hoà điểm thì intent khai báo trước thắng: "phiếu lương" phải thắng "lương"
  for (const [intent, words] of Object.entries(INTENT_KEYWORDS)) {
    const score = containsAny(folded, words).reduce((s, w) => s + (GENERIC_KEYWORDS.has(w) ? 0.5 : 1), 0);
    if (score > bestScore) {
      best = intent as Intent;
      bestScore = score;
    }
  }
  return best;
}

// Bảng dịch thuật ngữ cho chế độ dự phòng (không có Gemini để dịch VI→EN).
// Tài liệu trong rag.db là tiếng Anh: thiếu các từ này thì tìm từ khoá (BM25) không khớp được.
// Viết KHÔNG DẤU ở cột trái.
const GLOSSARY: [string, string][] = [
  ["lam thu", "unpaid trial shift"], ["thu viec", "unpaid trial"],
  ["tru luong", "deductions from pay"], ["tru tien", "deductions"],
  ["tien mat", "cash payment"], ["payslip", "pay slip"], ["phieu luong", "pay slip"],
  ["chu nhat", "Sunday penalty rates"], ["ngay le", "public holiday penalty rates"], ["tang ca", "overtime"],
  ["casual", "casual loading"], ["abn", "ABN sham contracting contractor"],
  ["ho chieu", "passport held"], ["huy visa", "visa cancelled"], ["sinh vien", "student visa work hours"],
  ["du hoc", "student visa"], ["duoi viec", "dismissal"], ["sa thai", "unfair dismissal"],
  ["bi thuong", "injured at work workers compensation"], ["do bao ho", "protective equipment"],
  ["gang tay", "gloves protective equipment"], ["hoa chat", "chemicals"],
  ["quay roi", "sexual harassment"], ["tuc tiu", "sexual comments harassment"], ["phan biet", "discrimination"],
];

export function glossaryTerms(message: string): string[] {
  const folded = foldVietnamese(message);
  return GLOSSARY.filter(([vi]) => containsAny(folded, [vi]).length).map(([, en]) => en);
}

export function fallbackNlu(message: string, emergency: string[]): NluResult {
  const intent = keywordIntent(message);
  const risk: RiskLevel = emergency.length ? "high" : "low";
  const terms = glossaryTerms(message);
  return {
    intent,
    entities: {},
    risk,
    needsReferral: risk === "high",
    // Thuật ngữ dịch được đứng trước: chúng là tín hiệu tìm kiếm mạnh nhất
    englishQuery: [...terms, INTENT_QUERY[intent], message].join(" ").slice(0, 400),
    emergencyKeywords: emergency,
    source: "fallback",
  };
}

// ---------- Bước 3 ----------

const SYSTEM_PROMPT = `You analyse messages from Vietnamese migrant workers in Australia for a workplace-rights support app.
Return JSON only.

intent (choose one):
- underpayment: paid below minimum/award rate, cash below rate, unpaid trials, deductions, penalty rates, overtime
- no_payslip: no pay slip, missing pay records
- unsafe: unsafe work, injury, chemicals, no protective equipment
- visa_threat: visa conditions, employer threatening visa, passport held, student work hour limits
- harassment: sexual harassment, bullying, discrimination, abuse
- unfair_dismissal: fired, shifts cut after complaining, notice
- contract_hours: contract, ABN/sham contracting, rosters, hours, leave
- general: anything else

risk:
- high: passport held, threats, violence, injury, forced work, sexual assault, self-harm, cannot leave
- medium: clear underpayment, visa pressure, harassment without violence, dismissal
- low: general questions

needsReferral: true when the worker should contact an official body or support service now.
englishQuery: rewrite the question as a short English search query using Australian workplace law terms
(award, casual loading, pay slip, penalty rates, unpaid trial, visa conditions, sham contracting...).
entities: only values explicitly stated. amount/hourlyRate in AUD numbers. abn = 11 digits if given.`;

const SCHEMA = {
  type: "OBJECT",
  properties: {
    intent: { type: "STRING", enum: [...INTENTS] },
    entities: {
      type: "OBJECT",
      properties: {
        employer: { type: "STRING" },
        amount: { type: "NUMBER" },
        hourlyRate: { type: "NUMBER" },
        hours: { type: "NUMBER" },
        visaType: { type: "STRING" },
        abn: { type: "STRING" },
      },
    },
    risk: { type: "STRING", enum: [...RISK_LEVELS] },
    needsReferral: { type: "BOOLEAN" },
    englishQuery: { type: "STRING" },
  },
  required: ["intent", "entities", "risk", "needsReferral", "englishQuery"],
};

// ---------- Bước 4 ----------

function positiveNumber(v: unknown): number | undefined {
  return typeof v === "number" && Number.isFinite(v) && v > 0 ? v : undefined;
}

function shortString(v: unknown, max = 120): string | undefined {
  return typeof v === "string" && v.trim() ? v.trim().slice(0, max) : undefined;
}

export function validateNlu(raw: unknown): Omit<NluResult, "emergencyKeywords" | "source"> | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  if (!INTENTS.includes(r.intent as Intent)) return null;
  if (!RISK_LEVELS.includes(r.risk as RiskLevel)) return null;
  const query = shortString(r.englishQuery, 400);
  if (!query) return null;

  const e = (r.entities && typeof r.entities === "object" ? r.entities : {}) as Record<string, unknown>;
  const abn = typeof e.abn === "string" ? e.abn.replace(/\D/g, "") : "";
  const entities: NluEntities = {
    employer: shortString(e.employer),
    amount: positiveNumber(e.amount),
    hourlyRate: positiveNumber(e.hourlyRate),
    hours: positiveNumber(e.hours),
    visaType: shortString(e.visaType, 40),
    abn: abn.length === 11 ? abn : undefined,
  };
  return {
    intent: r.intent as Intent,
    risk: r.risk as RiskLevel,
    needsReferral: r.needsReferral === true,
    englishQuery: query,
    entities: Object.fromEntries(Object.entries(entities).filter(([, v]) => v !== undefined)),
  };
}

// ---------- Bước 5 + hàm chính ----------

const RISK_ORDER: Record<RiskLevel, number> = { low: 0, medium: 1, high: 2 };

export function maxRisk(a: RiskLevel, b: RiskLevel): RiskLevel {
  return RISK_ORDER[a] >= RISK_ORDER[b] ? a : b;
}

export async function analyze(rawMessage: string): Promise<{ nlu: NluResult; error?: string; model?: string }> {
  const message = cleanMessage(rawMessage); // bước 1
  const emergency = scanEmergency(message); // bước 2

  if (isFakeMode()) return { nlu: fallbackNlu(message, emergency) };

  let validated: ReturnType<typeof validateNlu> = null;
  let error: string | undefined;
  let model: string | undefined;
  try {
    const result = await generateJson<unknown>({ // bước 3
      models: NLU_MODELS,
      system: SYSTEM_PROMPT,
      prompt: message,
      schema: SCHEMA,
      timeoutMs: TIMEOUT.nlu,
    });
    model = result.model;
    validated = validateNlu(result.data); // bước 4
    if (!validated) error = "JSON của Gemini không hợp lệ";
  } catch (e) {
    if (e instanceof GeminiAuthError) throw e; // sai key: báo lên trên, không giấu lỗi
    error = (e as Error).message;
  }

  if (!validated) return { nlu: fallbackNlu(message, emergency), error, model };

  const risk = emergency.length ? maxRisk(validated.risk, "high") : validated.risk; // bước 5
  return {
    nlu: {
      ...validated,
      risk,
      needsReferral: validated.needsReferral || risk === "high",
      emergencyKeywords: emergency,
      source: "gemini",
    },
    model,
  };
}
