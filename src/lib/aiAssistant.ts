import { ProblemTag } from "@/data/supportOrgs";
import { GoogleGenAI, Type } from "@google/genai";
import { AssistantResponse, ChatTurn } from "./assistantShared";
import { AI_MODELS } from "./aiConfig";
import { retrieveContext } from "./rag";

interface Scenario {
  id: string;
  keywords: string[];
  response: AssistantResponse;
}

export const scenarios: Scenario[] = [
  {
    id: "no_payslip",
    keywords: ["payslip", "phiếu lương", "phieu luong", "không có lương", "chứng từ lương"],
    response: {
      topic: "Không nhận được phiếu lương (payslip)",
      whatMightBeHappening:
        "Chủ của bạn có thể đang không tuân thủ nghĩa vụ cung cấp phiếu lương — đây là điều bắt buộc theo luật Úc, không phải là 'ưu ái' của chủ.",
      whyItMatters:
        "Theo Fair Work Act, người sử dụng lao động PHẢI cung cấp payslip trong vòng 1 ngày làm việc sau khi trả lương, ghi rõ giờ làm, mức lương, các khoản khấu trừ. Không có payslip khiến bạn rất khó chứng minh nếu bị trả thiếu lương sau này.",
      whatYouCanDo: [
        "Yêu cầu chủ cung cấp payslip bằng văn bản (tin nhắn/email để có bằng chứng bạn đã yêu cầu).",
        "Tự ghi lại giờ làm mỗi ngày và số tiền nhận được (sổ tay hoặc app điện thoại).",
        "Nếu chủ tiếp tục từ chối, bạn có thể liên hệ Fair Work Ombudsman để được tư vấn miễn phí.",
      ],
      evidenceToKeep: [
        "Tin nhắn/email yêu cầu payslip và phản hồi của chủ (nếu có)",
        "Ghi chép giờ làm hằng ngày (ngày, giờ bắt đầu/kết thúc)",
        "Ảnh chụp lịch làm việc (roster) nếu có",
        "Sao kê ngân hàng thể hiện tiền lương nhận được",
      ],
      helpTags: ["no_payslip", "underpayment"],
    },
  },
  {
    id: "cash_underpay",
    keywords: [
      "tiền mặt",
      "tien mat",
      "cash",
      "$20",
      "20 đô",
      "20 do",
      "lương thấp",
      "luong thap",
      "underpaid",
      "trả lương thấp",
    ],
    response: {
      topic: "Nghi ngờ bị trả lương thấp hơn quy định / trả tiền mặt",
      whatMightBeHappening:
        "Mức lương bạn mô tả có thể thấp hơn lương tối thiểu quốc gia hiện hành. Trả 'cash-in-hand' (tiền mặt, không giấy tờ) là một dấu hiệu phổ biến của tình trạng trả lương dưới mức quy định.",
      whyItMatters:
        "Mọi người lao động tại Úc — kể cả người giữ visa du học/working holiday — đều có quyền được trả ít nhất mức lương tối thiểu quốc gia theo giờ, bất kể hình thức trả (tiền mặt hay chuyển khoản). Trả tiền mặt không làm giảm quyền lợi này, nhưng khiến việc đòi lại tiền khó hơn nếu không có bằng chứng.",
      whatYouCanDo: [
        "Dùng công cụ 'Check My Job' trong app để so sánh mức lương của bạn với lương tối thiểu tham khảo hiện hành.",
        "Bắt đầu ghi chép lại mọi ca làm (ngày, giờ, số tiền nhận) từ hôm nay.",
        "Nếu có thể, hỏi khéo để chuyển sang nhận lương qua chuyển khoản ngân hàng — dễ chứng minh hơn.",
        "Liên hệ Fair Work Ombudsman (có hỗ trợ tiếng Việt qua phiên dịch, miễn phí) để được tư vấn cụ thể.",
      ],
      evidenceToKeep: [
        "Ghi chép giờ làm và số tiền nhận mỗi ca (viết tay hoặc trong Evidence Locker)",
        "Tin nhắn trao đổi về lương/giờ làm với chủ",
        "Ảnh chụp lịch làm việc",
        "Bất kỳ payslip hoặc biên nhận nào (nếu có)",
      ],
      helpTags: ["underpayment", "no_payslip"],
    },
  },
  {
    id: "sunday_no_extra",
    keywords: ["chủ nhật", "chu nhat", "sunday", "cuối tuần", "cuoi tuan", "weekend", "penalty rate", "phụ cấp"],
    response: {
      topic: "Làm Chủ Nhật/cuối tuần nhưng không được trả thêm",
      whatMightBeHappening:
        "Nhiều ngành nghề tại Úc (nhà hàng, bán lẻ, làm đẹp...) có quy định 'penalty rates' — mức lương cao hơn khi làm Chủ Nhật, thứ Bảy, hoặc ngày lễ, theo award (thỏa ước ngành) áp dụng.",
      whyItMatters:
        "Nếu công việc của bạn thuộc diện được hưởng penalty rate mà không được trả thêm, đây có thể là hành vi trả lương thiếu — bạn có quyền được truy thu phần chênh lệch.",
      whatYouCanDo: [
        "Tìm hiểu award (thỏa ước ngành) áp dụng cho công việc của bạn trên website Fair Work Ombudsman.",
        "Ghi lại rõ những ngày/giờ bạn đã làm Chủ Nhật, thứ Bảy, ngày lễ.",
        "Hỏi Fair Work Ombudsman để xác nhận mức phụ cấp đúng cho ngành và vị trí của bạn.",
      ],
      evidenceToKeep: [
        "Lịch làm việc ghi rõ ngày trong tuần",
        "Payslip hoặc sao kê lương theo từng ca",
        "Ghi chép cá nhân về giờ làm Chủ Nhật/lễ",
      ],
      helpTags: ["underpayment", "contract_hours"],
    },
  },
  {
    id: "student_visa_threat",
    keywords: [
      "sinh viên chỉ được",
      "student can only",
      "students can only",
      "visa du học",
      "đe dọa visa",
      "de doa visa",
      "báo di trú",
      "bao di tru",
      "threaten visa",
      "cancel visa",
      "report to immigration",
    ],
    response: {
      topic: "Chủ dùng thông tin sai lệch về visa hoặc đe dọa báo cáo di trú",
      whatMightBeHappening:
        "Chủ có thể đang đưa thông tin sai lệch về giới hạn giờ làm/lương của người giữ visa để ép bạn nhận lương thấp, hoặc dùng lời đe dọa về visa để bạn không dám lên tiếng. Đây là hình thức ép buộc, không phải là quy định luật thật.",
      whyItMatters:
        "Quyền được trả lương đúng quy định KHÔNG phụ thuộc vào loại visa bạn đang giữ. Việc đe dọa báo di trú để che giấu vi phạm luật lao động là hành vi cưỡng ép nghiêm trọng. Fair Work Ombudsman có chính sách hỗ trợ người giữ visa báo cáo vi phạm mà không ảnh hưởng đến tình trạng visa của họ trong nhiều trường hợp.",
      whatYouCanDo: [
        "Không cần hoảng sợ — hãy tìm hiểu kỹ thông tin trước khi phản ứng.",
        "Ghi lại chính xác những gì chủ đã nói (tin nhắn là tốt nhất, hoặc ghi chú thời gian/nội dung ngay sau khi nghe).",
        "Liên hệ Fair Work Ombudsman hoặc Migrant Workers Centre để được tư vấn miễn phí và bảo mật.",
        "Tự kiểm tra điều kiện visa thật của bạn trên website Bộ Di Trú (immi.homeaffairs.gov.au), đừng chỉ nghe qua lời chủ.",
      ],
      evidenceToKeep: [
        "Tin nhắn/email có nội dung đe dọa hoặc thông tin sai lệch về visa",
        "Ghi chú thời gian, địa điểm, nội dung cuộc nói chuyện (nếu chỉ nói miệng)",
        "Tên người làm chứng (nếu có ai khác nghe thấy)",
      ],
      helpTags: ["visa_threat", "underpayment"],
    },
  },
  {
    id: "unfair_dismissal",
    keywords: ["bị đuổi", "bi duoi", "sa thải", "sa thai", "fired", "terminated", "đuổi việc", "duoi viec", "cho nghỉ"],
    response: {
      topic: "Bị cho nghỉ việc/sa thải đột ngột",
      whatMightBeHappening:
        "Tuỳ vào loại hợp đồng và lý do, việc chấm dứt công việc đột ngột — đặc biệt không có thông báo trước hoặc không đúng quy trình — có thể là sa thải không công bằng (unfair dismissal) hoặc thiếu thông báo (notice) theo luật.",
      whyItMatters:
        "Người lao động thường có quyền được thông báo trước hoặc bồi thường thay thông báo khi bị cho nghỉ (tuỳ thời gian làm việc và loại hợp đồng). Có thời hạn nộp đơn khiếu nại (thường 21 ngày kể từ ngày nghỉ việc), nên hành động sớm là quan trọng.",
      whatYouCanDo: [
        "Ghi lại ngày chính xác và lý do được đưa ra khi cho bạn nghỉ việc.",
        "Không ký bất kỳ giấy tờ nào bạn chưa hiểu rõ.",
        "Liên hệ Fair Work Commission hoặc một trung tâm pháp lý càng sớm càng tốt — có thời hạn khiếu nại.",
      ],
      evidenceToKeep: [
        "Tin nhắn/email/thư thông báo nghỉ việc",
        "Hợp đồng lao động (nếu có)",
        "Ghi chép lại cuộc nói chuyện khi bị thông báo nghỉ việc",
        "Payslip gần nhất",
      ],
      helpTags: ["unfair_dismissal", "contract_hours"],
    },
  },
  {
    id: "unsafe",
    keywords: ["không an toàn", "khong an toan", "unsafe", "tai nạn", "tai nan", "chấn thương", "chan thuong", "nguy hiểm"],
    response: {
      topic: "Điều kiện làm việc không an toàn",
      whatMightBeHappening:
        "Bạn có thể đang làm việc trong môi trường chưa đảm bảo an toàn lao động (WHS/OHS) — ví dụ thiếu đào tạo, thiếu thiết bị bảo hộ, hoặc bị ép làm việc nguy hiểm.",
      whyItMatters:
        "Mọi người lao động có quyền làm việc trong môi trường an toàn, bất kể loại visa. Nếu bị chấn thương khi làm việc, bạn có thể có quyền được bồi thường (workers compensation).",
      whatYouCanDo: [
        "Báo cáo vấn đề an toàn cho chủ bằng văn bản nếu có thể.",
        "Nếu bị chấn thương, đi khám và giữ lại hồ sơ y tế, báo với cơ quan an toàn lao động của bang (WorkSafe/SafeWork).",
        "Liên hệ cơ quan an toàn lao động của bang bạn đang làm việc để được tư vấn.",
      ],
      evidenceToKeep: [
        "Ảnh chụp điều kiện làm việc không an toàn",
        "Ghi chép về sự cố/chấn thương (thời gian, địa điểm, diễn biến)",
        "Hồ sơ y tế liên quan (nếu có)",
        "Tin nhắn báo cáo vấn đề cho chủ",
      ],
      helpTags: ["unsafe", "general"],
    },
  },
  {
    id: "harassment",
    keywords: ["quấy rối", "quay roi", "harassment", "phân biệt đối xử", "phan biet doi xu", "discrimination", "bắt nạt", "bat nat"],
    response: {
      topic: "Quấy rối hoặc phân biệt đối xử tại nơi làm việc",
      whatMightBeHappening:
        "Bạn có thể đang trải qua hành vi quấy rối hoặc phân biệt đối xử — đây là điều không được phép xảy ra tại nơi làm việc, dù bạn đang giữ loại visa nào.",
      whyItMatters:
        "Luật Úc bảo vệ người lao động khỏi quấy rối và phân biệt đối xử dựa trên giới tính, chủng tộc, tuổi tác, tình trạng visa, v.v. Bạn có quyền khiếu nại mà không bị trả đũa.",
      whatYouCanDo: [
        "Ghi lại chi tiết từng sự việc (thời gian, địa điểm, người liên quan, nội dung).",
        "Nếu an toàn, báo cáo với cấp quản lý cao hơn hoặc bộ phận nhân sự bằng văn bản.",
        "Liên hệ một trung tâm pháp lý cộng đồng hoặc Fair Work Ombudsman để được tư vấn kín đáo, miễn phí.",
      ],
      evidenceToKeep: [
        "Ghi chép chi tiết từng sự việc kèm ngày giờ",
        "Tin nhắn/email liên quan",
        "Tên người làm chứng (nếu có)",
        "Ảnh chụp màn hình (nếu quấy rối qua tin nhắn/mạng xã hội)",
      ],
      helpTags: ["harassment", "general"],
    },
  },
  {
    id: "unpaid_trial",
    keywords: ["thử việc không lương", "thu viec khong luong", "unpaid trial", "unpaid shift", "làm thử không lương"],
    response: {
      topic: "Bị yêu cầu làm thử (trial shift) không lương",
      whatMightBeHappening:
        "'Thử việc không lương' kéo dài hoặc mang tính chất làm việc thật (phục vụ khách, vận hành máy móc...) thường KHÔNG hợp pháp tại Úc, trừ một số trường hợp rất ngắn và có mục đích đánh giá kỹ năng thuần tuý.",
      whyItMatters:
        "Nếu bạn thực sự làm việc có ích cho doanh nghiệp (dù gọi là 'thử việc'), bạn thường có quyền được trả lương cho thời gian đó.",
      whatYouCanDo: [
        "Ghi lại thời gian và công việc cụ thể bạn đã làm trong ca 'thử việc'.",
        "Hỏi thẳng chủ về việc trả lương cho ca thử việc, có tin nhắn/email làm bằng chứng.",
        "Liên hệ Fair Work Ombudsman để kiểm tra trường hợp cụ thể của bạn.",
      ],
      evidenceToKeep: [
        "Ghi chép ngày giờ và nội dung công việc đã làm trong ca thử việc",
        "Tin nhắn trao đổi về việc thử việc/lương",
        "Tên người quản lý trực tiếp hôm đó",
      ],
      helpTags: ["underpayment", "contract_hours"],
    },
  },
  {
    id: "deduction",
    keywords: ["bị trừ lương", "bi tru luong", "deduct", "khấu trừ", "khau tru", "trừ tiền", "tru tien"],
    response: {
      topic: "Bị trừ tiền lương (vỡ đồ, thiếu quỹ tiền mặt...)",
      whatMightBeHappening:
        "Việc tự ý trừ lương của bạn để bù cho hàng hỏng, thiếu hụt tiền quầy, hoặc lỗi trong công việc thường bị giới hạn chặt chẽ theo luật — phần lớn các khoản khấu trừ như vậy là KHÔNG hợp pháp nếu không có sự đồng ý hợp lệ bằng văn bản của bạn.",
      whyItMatters:
        "Chủ không được tự ý trừ lương của bạn để có lợi cho việc kinh doanh của họ, trừ khi luật cho phép hoặc bạn đồng ý bằng văn bản một cách tự nguyện (không bị ép buộc).",
      whatYouCanDo: [
        "Kiểm tra payslip xem khoản trừ được ghi rõ ràng chưa.",
        "Hỏi chủ lý do và căn cứ pháp lý của khoản trừ, yêu cầu bằng văn bản.",
        "Liên hệ Fair Work Ombudsman nếu bạn không đồng ý với khoản trừ này.",
      ],
      evidenceToKeep: [
        "Payslip thể hiện khoản bị trừ",
        "Tin nhắn/email giải thích lý do trừ lương (nếu có)",
        "Ghi chép sự việc dẫn đến khoản trừ (ví dụ sự cố tại nơi làm)",
      ],
      helpTags: ["underpayment", "no_payslip"],
    },
  },
];

const fallback: AssistantResponse = {
  topic: "Câu hỏi chung về quyền lợi tại nơi làm việc",
  whatMightBeHappening:
    "Mình chưa nhận diện được rõ tình huống cụ thể từ mô tả của bạn. Bạn có thể mô tả chi tiết hơn — ví dụ: bạn được trả bao nhiêu, làm bao nhiêu giờ, chủ nói gì, chuyện gì đã xảy ra.",
  whyItMatters:
    "Mỗi tình huống có thể liên quan đến các quyền lợi khác nhau (lương, giờ làm, an toàn, sa thải...). Mô tả càng cụ thể, gợi ý sẽ càng chính xác.",
  whatYouCanDo: [
    "Thử dùng công cụ 'Check My Job' để đánh giá nhanh tình huống lương/giờ làm của bạn.",
    "Xem qua mục 'Learn My Rights' để hiểu các quyền lợi cơ bản.",
    "Mô tả lại câu hỏi với nhiều chi tiết hơn ở đây.",
  ],
  evidenceToKeep: [
    "Nói chung, hãy luôn ghi chép giờ làm, lương nhận được, và lưu lại mọi tin nhắn/email liên quan đến công việc.",
  ],
  helpTags: ["general"],
};

const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY });

const PROBLEM_TAGS = [
  "underpayment", "no_payslip", "unsafe", "visa_threat",
  "harassment", "unfair_dismissal", "contract_hours", "general",
] as const;

const responseSchema = {
  type: Type.OBJECT,
  properties: {
    topic: { type: Type.STRING },
    whatMightBeHappening: { type: Type.STRING },
    whyItMatters: { type: Type.STRING },
    whatYouCanDo: { type: Type.ARRAY, items: { type: Type.STRING } },
    evidenceToKeep: { type: Type.ARRAY, items: { type: Type.STRING } },
    helpTags: { type: Type.ARRAY, items: { type: Type.STRING, enum: PROBLEM_TAGS } },
  },
  required: ["topic", "whatMightBeHappening", "whyItMatters", "whatYouCanDo", "evidenceToKeep", "helpTags"],
};

const knowledgeBase = scenarios
  .map((s) => `- ${s.response.topic}: ${s.response.whyItMatters}`)
  .join("\n");

function buildSystemInstruction(ragChunks: string[]): string {
  const ragSection = ragChunks.length > 0
    ? `\n\nThông tin luật tham khảo thêm (trích Fair Work Ombudsman, ưu tiên dùng nếu liên quan trực tiếp đến câu hỏi):\n${ragChunks.join("\n\n---\n\n")}`
    : "";

  return `Bạn là trợ lý AI về quyền lợi lao động cho người lao động Việt Nam tại Úc, trong app "Bạn Đồng Hành".
Chỉ trả lời bằng tiếng Việt. Đây KHÔNG phải tư vấn pháp lý chính thức — luôn nhắc người dùng kiểm tra lại với Fair Work Ombudsman khi cần.
Dựa trên các kiến thức đã được kiểm chứng sau (không tự bịa số liệu luật khác):
${knowledgeBase}${ragSection}
Trả lời đúng theo JSON schema được cung cấp.`;
}

/** Kiểm tra JSON Gemini trả về có đủ field cần thiết không, tránh crash nếu model trả thiếu. */
function isValidResponse(x: unknown): x is AssistantResponse {
  if (!x || typeof x !== "object") return false;
  const r = x as Record<string, unknown>;
  return (
    typeof r.topic === "string" &&
    typeof r.whatMightBeHappening === "string" &&
    typeof r.whyItMatters === "string" &&
    Array.isArray(r.whatYouCanDo) &&
    Array.isArray(r.evidenceToKeep) &&
    Array.isArray(r.helpTags)
  );
}




export function askAssistant(message: string): AssistantResponse {
  const normalized = message.toLowerCase();
  for (const scenario of scenarios) {
    if (scenario.keywords.some((kw) => normalized.includes(kw.toLowerCase()))) {
      return scenario.response;
    }
  }
  return fallback;
}


export async function askAssistantSmart(
  message: string,
  history: ChatTurn[] = []
): Promise<AssistantResponse> {
  if (!process.env.GEMINI_API_KEY) {
    return askAssistant(message);
  }

  // MỚI: lấy context RAG liên quan đến câu hỏi trước khi gọi model
  const ragChunks = await retrieveContext(message);
  const systemInstruction = buildSystemInstruction(ragChunks);

  const historyContents = history.slice(-6).map((turn) => ({
    role: turn.role === "user" ? "user" : "model",
    parts: [{ text: turn.role === "user" ? turn.content : summarizeForHistory(turn.content) }],
  }));
  const contents = [...historyContents, { role: "user", parts: [{ text: message }] }];

  for (const model of AI_MODELS) {
    try {
      const result = await ai.models.generateContent({
        model,
        contents,
        config: { systemInstruction, responseMimeType: "application/json", responseSchema },
      });

      const parsed = JSON.parse(result.text!);
      if (!isValidResponse(parsed)) throw new Error(`Model "${model}" trả JSON thiếu field`);

      return parsed;
    } catch (err) {
      console.error(`Model "${model}" lỗi, thử model kế tiếp:`, err);
    }
  }

  console.error("Tất cả model trong AI_MODELS đều lỗi, dùng rule-based fallback.");
  return askAssistant(message);
}

/** Tóm tắt câu trả lời cũ (JSON) thành 1 câu ngắn để nhét vào history, tránh prompt phình to. */
function summarizeForHistory(assistantJson: string): string {
  try {
    const r = JSON.parse(assistantJson) as AssistantResponse;
    return `[Đã tư vấn về: ${r.topic}]`;
  } catch {
    return "[phản hồi trước]";
  }
}

