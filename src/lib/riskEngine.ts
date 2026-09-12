// Simple, transparent rule-based risk engine for "Check My Job".
// Reference rates: Fair Work Ombudsman national minimum wage, effective 1 July 2026.
// Source: https://www.fairwork.gov.au/pay-and-wages/minimum-wages
export const NATIONAL_MIN_WAGE = 26.44; // per hour, full-time/part-time/permanent
export const CASUAL_MIN_WAGE = 33.05; // per hour, includes 25% casual loading
export const MIN_WAGE_EFFECTIVE_DATE = "01/07/2026";

export type PayUnit = "per_hour" | "per_week" | "flat_regardless_of_hours";
export type EmploymentType = "Casual" | "Part-time" | "Full-time" | "Contractor / ABN" | "Not sure";
export type PaymentMethod = "Bank transfer" | "Cash" | "Mixed (cash + bank)" | "Not sure";
export type HasPayslips = "yes" | "no" | "not_sure";
export type RiskLevel = "ok" | "issue" | "high";

export interface JobCheckInput {
  industry: string;
  role?: string;
  employmentType: EmploymentType;
  payAmount: number;
  payUnit: PayUnit;
  hoursPerWeek?: number;
  workingDays: string[];
  paymentMethod: PaymentMethod;
  visa: string;
  hasPayslips: HasPayslips;
}

export interface RiskReason {
  points: number;
  message: string;
}

export interface JobCheckResult {
  level: RiskLevel;
  score: number;
  estimatedHourlyRate: number | null;
  applicableMinWage: number;
  reasons: RiskReason[];
  positives: string[];
  notes: string[];
}

function round2(n: number) {
  return Math.round(n * 100) / 100;
}

export function assessJob(input: JobCheckInput): JobCheckResult {
  const reasons: RiskReason[] = [];
  const positives: string[] = [];
  const notes: string[] = [];

  const applicableMinWage =
    input.employmentType === "Casual" ? CASUAL_MIN_WAGE : NATIONAL_MIN_WAGE;

  let estimatedHourlyRate: number | null = null;
  if (input.payUnit === "per_hour") {
    estimatedHourlyRate = input.payAmount;
  } else if (input.payUnit === "per_week") {
    if (input.hoursPerWeek && input.hoursPerWeek > 0) {
      estimatedHourlyRate = round2(input.payAmount / input.hoursPerWeek);
    }
  }

  let score = 0;

  if (input.payUnit === "flat_regardless_of_hours") {
    score += 40;
    reasons.push({
      points: 40,
      message:
        "Bạn được trả một khoản cố định bất kể làm bao nhiêu giờ — cách trả lương này thường khiến mức lương thực tế theo giờ thấp hơn lương tối thiểu, đặc biệt nếu giờ làm thay đổi.",
    });
  } else if (estimatedHourlyRate !== null) {
    if (estimatedHourlyRate < applicableMinWage * 0.8) {
      score += 50;
      reasons.push({
        points: 50,
        message: `Mức lương ước tính khoảng $${estimatedHourlyRate}/giờ, thấp hơn nhiều so với lương tối thiểu tham khảo ($${applicableMinWage}/giờ cho ${input.employmentType === "Casual" ? "casual" : "nhân viên thường"}).`,
      });
    } else if (estimatedHourlyRate < applicableMinWage) {
      score += 30;
      reasons.push({
        points: 30,
        message: `Mức lương ước tính khoảng $${estimatedHourlyRate}/giờ, thấp hơn lương tối thiểu tham khảo ($${applicableMinWage}/giờ).`,
      });
    } else {
      positives.push(
        `Mức lương ước tính khoảng $${estimatedHourlyRate}/giờ, đáp ứng lương tối thiểu quốc gia tham khảo ($${applicableMinWage}/giờ).`
      );
    }
  } else {
    notes.push(
      "Chưa đủ thông tin để ước tính lương theo giờ (thiếu số giờ làm/tuần) — hãy điền thêm để có đánh giá chính xác hơn."
    );
  }

  if (input.paymentMethod === "Cash") {
    score += 15;
    reasons.push({
      points: 15,
      message:
        "Nhận lương bằng tiền mặt khiến việc chứng minh thu nhập khó hơn nếu sau này có tranh chấp — hãy tự ghi chép lại giờ làm và số tiền nhận mỗi lần.",
    });
  } else if (input.paymentMethod === "Mixed (cash + bank)") {
    score += 8;
    reasons.push({
      points: 8,
      message: "Một phần lương trả bằng tiền mặt — nên ghi chép rõ phần này để có bằng chứng đầy đủ.",
    });
  }

  if (input.hasPayslips === "no") {
    score += 20;
    reasons.push({
      points: 20,
      message:
        "Không nhận được phiếu lương (payslip). Theo luật Úc, người sử dụng lao động phải cung cấp payslip trong vòng 1 ngày làm việc sau khi trả lương.",
    });
  } else if (input.hasPayslips === "not_sure") {
    score += 8;
    reasons.push({
      points: 8,
      message: "Bạn chưa chắc có nhận payslip hay không — hãy kiểm tra lại email/tin nhắn hoặc hỏi trực tiếp chủ.",
    });
  }

  if (input.paymentMethod === "Cash" && input.hasPayslips === "no") {
    score += 10;
    reasons.push({
      points: 10,
      message: "Kết hợp trả tiền mặt và không có payslip là dấu hiệu cảnh báo phổ biến trong các trường hợp trả lương thấp hơn quy định.",
    });
  }

  if (input.employmentType === "Contractor / ABN") {
    notes.push(
      "Bạn được trả qua ABN (hợp đồng) nhưng nếu bạn phải theo giờ giấc cố định, chịu sự quản lý trực tiếp như nhân viên, đây có thể là 'sham contracting' (giả danh hợp đồng để né nghĩa vụ với nhân viên) — nên tìm hiểu thêm hoặc hỏi Fair Work Ombudsman."
    );
  }

  if (input.visa === "Student" && input.hoursPerWeek && input.hoursPerWeek > 24) {
    notes.push(
      "Thị thực du học sinh (500) thường có giới hạn giờ làm trong kỳ học (hiện là 48 giờ/2 tuần, tương đương ~24 giờ/tuần). Hãy tự kiểm tra điều kiện visa của bạn (điều kiện 8104) để tránh vi phạm — đây là trách nhiệm của bạn, không phải của chủ."
    );
  }

  if (
    input.workingDays.some((d) => d === "Chủ nhật" || d === "Ngày lễ") &&
    estimatedHourlyRate !== null &&
    estimatedHourlyRate <= applicableMinWage
  ) {
    notes.push(
      "Bạn có làm Chủ nhật/ngày lễ. Nhiều ngành có 'penalty rates' (phụ cấp làm ngày cuối tuần/lễ) cao hơn lương ngày thường — hãy kiểm tra award (thỏa ước ngành) áp dụng cho công việc của bạn."
    );
  }

  score = Math.min(score, 100);

  let level: RiskLevel = "ok";
  if (score >= 50) level = "high";
  else if (score >= 20) level = "issue";

  return {
    level,
    score,
    estimatedHourlyRate,
    applicableMinWage,
    reasons,
    positives,
    notes,
  };
}
