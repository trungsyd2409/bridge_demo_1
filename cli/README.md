# Thử trợ lý AI bằng dòng lệnh

Không cần giao diện, không cần đăng nhập, không cần database người dùng.
`cli/ask.mts` gọi thẳng `askAssistant(message, profile)` — đúng hàm mà `/api/assistant` dùng.

## Lệnh

```bash
npm run ask -- "Chủ không đưa payslip"                          # hỏi một câu
npm run ask -- "làm bao nhiêu giờ" --visa student                # kèm hồ sơ (mã)
npm run ask -- "làm bao nhiêu giờ" --visa "Du học sinh (Student)" # hoặc nhãn onboarding
npm run ask -- "..." --trace                                     # xem từng bước + thời gian
npm run ask -- "..." --json                                      # JSON đúng định dạng API trả cho giao diện
npm run ask                                                      # hỏi liên tục (/help để xem lệnh)
npm run ask:eval                                                 # chạy cli/cases.jsonl + kiểm tra tự động
npm run ask -- --fake ...                                        # không gọi Gemini
npm run ask -- --db test/fixtures/sample-rag.db --fake ...       # dùng rag.db thử
npm run ask -- --models                                          # model nào key của bạn dùng được
```

## Luôn ra "mẫu dự phòng"?

Chạy `npm run ask -- "câu hỏi" --trace` rồi tìm bước có dấu ✗. Nếu lỗi là 404 hoặc
"no longer available to new users": Google đã khoá model đó với project của bạn. Chạy
`npm run ask -- --models`, dán 3 dòng `AI_*_MODELS` nó gợi ý vào `.env.local`, khởi động lại `npm run dev`.

Hồ sơ: `--visa`, `--industry`, `--employment`, `--state`. Nhận mã (`student`, `hospitality`,
`casual`, `NSW`) hoặc nhãn tiếng Việt mà trang onboarding lưu.

## Bộ câu hỏi `cli/cases.jsonl`

Mỗi dòng: `{"id", "message", "profile"?, "expect"?, "note"?}`. Có câu sai kỳ vọng thì lệnh trả mã lỗi 1.

`expect` có thể gồm:

| Trường | Kiểm gì |
|---|---|
| `intent`, `risk`, `urgent`, `mode` | nhãn phân loại |
| `source` | **ít nhất một** nguồn được trích khớp regex |
| `sourceAll` | **mọi** nguồn được trích phải khớp regex — bắt lỗi trích tài liệu lạc chủ đề |
| `grounding` | mức grounding phải đúng bằng giá trị này |
| `notInsufficient` | không được trả lời "chưa đủ nguồn" |
| `contains` | mảng regex **phải** xuất hiện trong câu trả lời (dùng cho con số bắt buộc đúng) |
| `notContains` | mảng regex **không được** xuất hiện (số liệu cũ, khẳng định quá chắc) |
| `noBareMoney` | nêu số tiền thì bắt buộc có trích dẫn, và không được vừa nêu số vừa khai "chưa đủ nguồn" |

Vì sao cần nhiều hơn `intent`: bộ 14 câu ban đầu đạt 14/14 trong khi trợ lý vẫn trả lời sai —
nó chỉ kiểm nhãn, không kiểm nội dung. Ví dụ câu `dis1` pass nhưng 4 nguồn được trích đều là
tài liệu về payslip, chẳng liên quan gì tới sa thải. `sourceAll` và `contains` bắt được loại lỗi đó.
Mỗi lần phát hiện trợ lý trả lời sai, thêm câu đó vào file: lần sau sửa code, lỗi cũ không quay lại.
Báo cáo chi tiết lưu ở `cli/reports/` (không commit).

## Thoả thuận dữ liệu với phần lưu trữ người dùng

Phần AI chỉ cần **câu hỏi + 4 trường hồ sơ**, không cần tên, email hay dữ liệu cá nhân khác:

```ts
askAssistant(message: string, profile: {
  visa?: "student" | "whv" | "temp_work" | "pr";
  industry?: "hospitality" | "beauty" | "cleaning" | "retail" | "farm";
  employment?: "casual" | "part_time" | "full_time" | "contractor";
  state?: "NSW" | "VIC" | "QLD" | "WA" | "SA" | "TAS" | "ACT" | "NT";
})
```

- Bảng `profiles` đang lưu NHÃN tiếng Việt: `profileFromOnboarding()` (src/lib/assistant/legacy.ts) đổi sang mã.
  Đổi nhãn trên trang onboarding thì phải cập nhật quy tắc trong file đó (test "adapter cho app cũ" sẽ báo).
- Câu hỏi được gửi tới Gemini: KHÔNG ghép tên, email, số điện thoại hay nội dung Evidence Locker vào `message`.
- Phần AI không lưu gì. Lưu lịch sử chat là việc của `/api/assistant/route.ts` (bảng `ai_messages`).
