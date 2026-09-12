/** Lọc hồ sơ người dùng gửi lên: chỉ giữ giá trị khớp taxonomy của pipeline. */
import type { UserProfile } from "./types";

const ALLOWED = {
  visa: ["student", "whv", "temp_work", "pr"],
  industry: ["hospitality", "beauty", "cleaning", "retail", "farm"],
  employment: ["casual", "part_time", "full_time", "contractor"],
  state: ["NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"],
} as const;

/** Chỉ giữ giá trị hợp lệ: dữ liệu từ trình duyệt không được tin tuyệt đối. */
export function sanitizeProfile(raw: unknown): UserProfile {
  if (!raw || typeof raw !== "object") return {};
  const r = raw as Record<string, unknown>;
  const pick = <K extends keyof typeof ALLOWED>(key: K) => {
    const v = typeof r[key] === "string" ? (r[key] as string) : undefined;
    return v && (ALLOWED[key] as readonly string[]).includes(v) ? v : undefined;
  };
  return {
    visa: pick("visa") as UserProfile["visa"],
    industry: pick("industry") as UserProfile["industry"],
    employment: pick("employment") as UserProfile["employment"],
    state: pick("state"),
  };
}
