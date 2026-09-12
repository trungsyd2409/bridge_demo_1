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

Mỗi dòng: `{"id", "message", "profile"?, "expect"?}`. `expect` có thể gồm `intent`, `urgent`,
`source` (regex khớp nguồn được trích), `notInsufficient`. Có câu sai kỳ vọng thì lệnh trả mã lỗi 1.
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
