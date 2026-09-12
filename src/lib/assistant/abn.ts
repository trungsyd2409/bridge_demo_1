/**
 * ABN Lookup: nguồn bằng chứng dạng API (priority 1). TUỲ CHỌN.
 * Chỉ chạy khi có ABN_LOOKUP_GUID trong .env.local (đăng ký miễn phí tại abr.business.gov.au,
 * mục Web Services) VÀ người dùng nhắc tới một ABN 11 chữ số.
 *
 * Dịch vụ JSON của ABR trả về dạng JSONP: callback({...}). Hàm parseAbnResponse bóc lớp đó.
 */
import { TIMEOUT } from "./config";
import type { Evidence } from "./types";

const ENDPOINT = "https://abr.business.gov.au/json/AbnDetails.aspx";

export interface AbnDetails {
  abn: string;
  status: string; // "Active" | "Cancelled"
  entityName: string;
  entityType: string;
  state: string;
  gstRegistered: boolean;
}

/** Kiểm tra ABN hợp lệ theo thuật toán checksum của ATO (bắt lỗi gõ nhầm trước khi gọi API). */
export function isValidAbn(abn: string): boolean {
  const digits = abn.replace(/\D/g, "");
  if (digits.length !== 11) return false;
  const weights = [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19];
  const nums = digits.split("").map(Number);
  nums[0] -= 1;
  return nums.reduce((sum, n, i) => sum + n * weights[i], 0) % 89 === 0;
}

export function parseAbnResponse(text: string): AbnDetails | null {
  const json = text.trim().replace(/^[^(]*\(/, "").replace(/\);?\s*$/, "");
  const d = JSON.parse(json) as Record<string, unknown>;
  if (d.Message) return null; // ABR báo lỗi, ví dụ không tìm thấy
  const names = Array.isArray(d.BusinessName) ? (d.BusinessName as string[]) : [];
  return {
    abn: String(d.Abn ?? ""),
    status: String(d.AbnStatus ?? "Unknown"),
    entityName: String(d.EntityName || names[0] || "Unknown"),
    entityType: String(d.EntityTypeName ?? ""),
    state: String(d.AddressState ?? ""),
    gstRegistered: Boolean(d.Gst),
  };
}

export async function abnEvidence(abn: string | undefined): Promise<Evidence | null> {
  const guid = process.env.ABN_LOOKUP_GUID?.trim();
  if (!guid || !abn || !isValidAbn(abn)) return null;

  const url = `${ENDPOINT}?abn=${encodeURIComponent(abn)}&callback=callback&guid=${encodeURIComponent(guid)}`;
  const res = await fetch(url, { signal: AbortSignal.timeout(TIMEOUT.abn) });
  if (!res.ok) throw new Error(`ABN Lookup HTTP ${res.status}`);
  const details = parseAbnResponse(await res.text());
  if (!details) return null;

  return {
    kind: "api",
    priority: 1,
    title: `ABN ${details.abn}`,
    content:
      `ABN ${details.abn} status: ${details.status}. Registered name: ${details.entityName}` +
      `${details.entityType ? ` (${details.entityType})` : ""}${details.state ? `, ${details.state}` : ""}. ` +
      `GST registered: ${details.gstRegistered ? "yes" : "no"}.`,
    source: "Australian Business Register (ABN Lookup)",
    url: `https://abr.business.gov.au/ABN/View?abn=${details.abn}`,
  };
}
