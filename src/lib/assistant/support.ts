/**
 * Danh bạ hỗ trợ theo intent + khối cảnh báo khẩn cấp.
 * Khối khẩn cấp được tạo bằng CODE, không phụ thuộc LLM: kể cả khi Gemini lỗi,
 * người đang gặp nguy vẫn thấy số điện thoại cần gọi.
 *
 * App đã có src/data/supportOrgs.ts với helpTags: có thể thay CONTACTS bằng dữ liệu đó.
 */
import type { Intent, NluResult, SupportContact, UserProfile } from "./types";

const C = {
  fwo: { name: "Fair Work Ombudsman", phone: "13 13 94", url: "https://www.fairwork.gov.au", note: "Lương, payslip, quyền lợi — miễn phí, không ảnh hưởng visa" },
  fwc: { name: "Fair Work Commission", phone: "1300 799 675", url: "https://www.fwc.gov.au", note: "Khiếu nại bị đuổi việc — thời hạn 21 ngày" },
  ahrc: { name: "Australian Human Rights Commission", phone: "1300 656 419", url: "https://humanrights.gov.au", note: "Quấy rối, phân biệt đối xử" },
  safeWorkNsw: { name: "SafeWork NSW", phone: "13 10 50", url: "https://www.safework.nsw.gov.au", note: "An toàn lao động tại NSW" },
  safeWorkAus: { name: "Safe Work Australia", url: "https://www.safeworkaustralia.gov.au", note: "Tìm cơ quan an toàn lao động của bang bạn" },
  tis: { name: "TIS National (phiên dịch)", phone: "131 450", note: "Phiên dịch tiếng Việt miễn phí khi gọi các cơ quan trên" },
  emergency: { name: "Cấp cứu / Cảnh sát", phone: "000", note: "Khi đang gặp nguy hiểm" },
  police: { name: "Cảnh sát (không khẩn cấp)", phone: "131 444", note: "Báo việc bị giữ hộ chiếu, đe doạ" },
  lifeline: { name: "Lifeline", phone: "13 11 14", note: "Hỗ trợ tâm lý 24/7" },
} satisfies Record<string, SupportContact>;

export function contactsFor(intent: Intent, profile: UserProfile): SupportContact[] {
  const safety = profile.state?.toUpperCase() === "NSW" ? C.safeWorkNsw : C.safeWorkAus;
  const byIntent: Record<Intent, SupportContact[]> = {
    underpayment: [C.fwo],
    no_payslip: [C.fwo],
    visa_threat: [C.fwo],
    contract_hours: [C.fwo],
    unfair_dismissal: [C.fwc, C.fwo],
    unsafe: [safety, C.fwo],
    harassment: [C.ahrc, C.fwo],
    general: [C.fwo],
  };
  return [...byIntent[intent], C.tis];
}

export function urgentBlock(nlu: NluResult, selfHarm: boolean) {
  if (selfHarm) {
    return {
      show: true,
      message: "Nếu bạn đang nghĩ đến việc làm hại bản thân, hãy gọi ngay Lifeline hoặc 000. Bạn không phải đối mặt một mình.",
      contacts: [C.lifeline, C.emergency, C.tis],
    };
  }
  if (nlu.risk === "high") {
    return {
      show: true,
      message: "Tình huống của bạn có dấu hiệu nghiêm trọng. Nếu đang gặp nguy hiểm, gọi 000 ngay. Liên hệ các cơ quan dưới đây càng sớm càng tốt — gọi họ KHÔNG làm visa của bạn bị huỷ.",
      contacts: [C.emergency, C.police, C.fwo, C.tis],
    };
  }
  return { show: false, message: "", contacts: [] as SupportContact[] };
}
