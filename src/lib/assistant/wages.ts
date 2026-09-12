/**
 * Lương tối thiểu quốc gia: nguồn bằng chứng dạng "tra bảng" (priority 2).
 * Con số là DỮ LIỆU, không để LLM tự nhớ hay tự tính: so sánh lương làm bằng code.
 *
 * Cập nhật mỗi năm sau Annual Wage Review (hiệu lực 1/7). Khi có MAPD API
 * (developer.fwc.gov.au) thì thay bảng này bằng dữ liệu theo từng award.
 */
import type { Evidence, NluResult } from "./types";

export interface WageRate {
  effectiveFrom: string; // ISO
  hourly: number; // lương tối thiểu quốc gia / giờ (người lớn, không phải casual)
  casualLoading: number; // 0.25 = 25%
}

// Theo dữ liệu đang dùng trong app (Fair Work Ombudsman, hiệu lực 01/07/2026).
export const NATIONAL_MINIMUM_WAGES: WageRate[] = [
  { effectiveFrom: "2026-07-01", hourly: 26.44, casualLoading: 0.25 },
];

export const WAGE_SOURCE = {
  source: "Fair Work Ombudsman",
  url: "https://www.fairwork.gov.au",
};

export function currentRate(today = new Date()): WageRate {
  const iso = today.toISOString().slice(0, 10);
  const valid = NATIONAL_MINIMUM_WAGES.filter((r) => r.effectiveFrom <= iso)
    .sort((a, b) => b.effectiveFrom.localeCompare(a.effectiveFrom));
  return valid[0] ?? NATIONAL_MINIMUM_WAGES[0];
}

export const round2 = (n: number) => Math.round(n * 100) / 100;

export function casualRate(rate: WageRate): number {
  return round2(rate.hourly * (1 + rate.casualLoading));
}

export interface WageComparison {
  reported: number;
  minimum: number;
  isCasual: boolean;
  shortfallPerHour: number; // > 0 nghĩa là bị trả thấp hơn mức tối thiểu
}

export function compareWage(reported: number, isCasual: boolean, rate = currentRate()): WageComparison {
  const minimum = isCasual ? casualRate(rate) : rate.hourly;
  return { reported, minimum, isCasual, shortfallPerHour: round2(Math.max(0, minimum - reported)) };
}

/** Tạo bằng chứng lương khi câu hỏi liên quan đến lương. */
export function wageEvidence(nlu: NluResult, employment?: string): Evidence | null {
  const rate = currentRate();
  const relevant = nlu.intent === "underpayment" || nlu.entities.hourlyRate !== undefined;
  if (!relevant) return null;

  const lines = [
    `National minimum wage from ${rate.effectiveFrom}: $${rate.hourly.toFixed(2)} per hour for adult employees.`,
    `Casual employees: at least $${casualRate(rate).toFixed(2)} per hour (includes ${rate.casualLoading * 100}% casual loading).`,
    "Many awards set HIGHER rates than the national minimum, plus penalty rates for weekends, public holidays and nights. Junior and apprentice rates can be lower.",
  ];
  const reported = nlu.entities.hourlyRate;
  if (reported !== undefined) {
    const cmp = compareWage(reported, employment === "casual", rate);
    lines.push(
      cmp.shortfallPerHour > 0
        ? `The worker reports $${reported.toFixed(2)}/hour, which is $${cmp.shortfallPerHour.toFixed(2)}/hour BELOW the ${cmp.isCasual ? "casual " : ""}minimum of $${cmp.minimum.toFixed(2)}.`
        : `The worker reports $${reported.toFixed(2)}/hour, which is not below the ${cmp.isCasual ? "casual " : ""}national minimum of $${cmp.minimum.toFixed(2)} (their award may still require more).`,
    );
  }
  return {
    kind: "db",
    priority: 2,
    title: "National minimum wage (lookup table)",
    content: lines.join(" "),
    ...WAGE_SOURCE,
  };
}
