/**
 * Thử trợ lý AI từ dòng lệnh — không cần giao diện, không cần đăng nhập, không cần database người dùng.
 * Gọi thẳng askAssistant(message, profile) giống hệt API /api/assistant.
 *
 *   npm run ask -- "Chủ không đưa payslip"                     hỏi một câu
 *   npm run ask -- "làm bao nhiêu giờ" --visa student           kèm hồ sơ
 *   npm run ask -- "..." --visa "Du học sinh (Student)"          nhãn onboarding cũng được
 *   npm run ask -- "..." --trace                                 xem từng bước + thời gian
 *   npm run ask -- "..." --json                                  in JSON gốc (để gửi cho người làm giao diện)
 *   npm run ask                                                  chế độ hỏi liên tục
 *   npm run ask -- --file cli/cases.jsonl                        chạy bộ câu hỏi + kiểm tra tự động
 *   npm run ask -- --fake ...                                    không gọi Gemini (dùng rag.db vector giả)
 *   npm run ask -- --models                                      model nào key của bạn dùng được thật
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { createInterface } from "node:readline/promises";
import { parseArgs } from "node:util";

// ---------- 1. Đọc tham số và .env.local TRƯỚC khi nạp module trợ lý ----------
// (config.ts đọc biến môi trường ngay lúc được import)

const { values: opt, positionals } = parseArgs({
  allowPositionals: true,
  options: {
    visa: { type: "string" },
    industry: { type: "string" },
    employment: { type: "string" },
    state: { type: "string" },
    file: { type: "string", short: "f" },
    trace: { type: "boolean", short: "t", default: false },
    json: { type: "boolean", default: false },
    fake: { type: "boolean", default: false },
    db: { type: "string" },
    "no-color": { type: "boolean", default: false },
    models: { type: "boolean", default: false },
    help: { type: "boolean", short: "h", default: false },
  },
});

if (existsSync(".env.local")) process.loadEnvFile(".env.local");
if (opt.fake) process.env.RAG_FAKE_GEMINI = "1";
if (opt.db) process.env.RAG_DB_PATH = path.resolve(opt.db);

const { askAssistant } = await import("../src/lib/assistant/index");
const { sanitizeProfile } = await import("../src/lib/assistant/profile");
const { profileFromOnboarding, toLegacyResponse } = await import("../src/lib/assistant/legacy");
const { RAG_DB_PATH, isFakeMode, NLU_MODELS, ANSWER_MODELS, EMBED_MODEL, EMBED_DIM } = await import("../src/lib/assistant/config");
type UserProfile = import("../src/lib/assistant/types").UserProfile;
type AssistantResponse = import("../src/lib/assistant/types").AssistantResponse;
type TraceStep = import("../src/lib/assistant/types").TraceStep;

// ---------- 2. Màu chữ ----------

const useColor = process.stdout.isTTY && !opt["no-color"];
const paint = (code: number) => (s: string) => (useColor ? `\x1b[${code}m${s}\x1b[0m` : s);
const c = { bold: paint(1), dim: paint(2), red: paint(31), green: paint(32), yellow: paint(33), cyan: paint(36) };

// ---------- 3. Hồ sơ: nhận cả mã lẫn nhãn onboarding ----------

const PROFILE_KEYS = ["visa", "industry", "employment", "state"] as const;
type ProfileKey = (typeof PROFILE_KEYS)[number];

/** "student" giữ nguyên; "Du học sinh (Student)" -> "student"; giá trị lạ -> undefined + cảnh báo. */
function normalizeProfile(raw: Partial<Record<ProfileKey, string>>): UserProfile {
  const profile: UserProfile = {};
  for (const key of PROFILE_KEYS) {
    const value = raw[key]?.trim();
    if (!value) continue;
    const asCode = sanitizeProfile({ [key]: key === "state" ? value.toUpperCase() : value })[key];
    const asLabel = key === "state" ? undefined : profileFromOnboarding({ [key]: value })[key];
    const result = asCode ?? asLabel;
    if (result) (profile as Record<string, string>)[key] = result;
    else console.log(c.yellow(`! ${key}="${value}" không nhận ra được — bỏ qua (không lọc theo ${key})`));
  }
  return profile;
}

const describeProfile = (p: UserProfile) =>
  Object.entries(p).filter(([, v]) => v).map(([k, v]) => `${k}=${v}`).join(", ") || "trống (không lọc)";

// ---------- 4. In kết quả ----------

function printTrace(trace: TraceStep[]) {
  console.log(c.bold("\nNhật ký xử lý:"));
  for (const t of trace) {
    const mark = t.ok ? c.green("✓") : c.red("✗");
    const detail = t.detail === undefined ? "" : typeof t.detail === "string" ? t.detail : JSON.stringify(t.detail);
    console.log(`  ${mark} ${t.step.padEnd(28)} ${String(t.ms).padStart(5)} ms  ${c.dim(detail.slice(0, 160))}`);
  }
}

function printResponse(r: AssistantResponse, trace: TraceStep[], ms: number) {
  if (opt.json) {
    // Định dạng mà API /api/assistant trả cho giao diện
    console.log(JSON.stringify({ response: toLegacyResponse(r) }, null, 2));
    return;
  }
  const a = r.answer;
  const engine = r.mode === "llm" ? c.green("Gemini") : c.yellow("mẫu dự phòng");
  const grounding = { grounded: c.green("có nguồn"), partial: c.yellow("nguồn một phần"), insufficient: c.red("chưa đủ nguồn") }[a.grounding];
  console.log(`\n${c.dim(`intent=${r.intent} · rủi ro=${r.risk} · ${ms} ms ·`)} ${engine} · ${grounding}`);

  if (r.urgent.show) {
    console.log(c.red(c.bold(`\n⚠ ${r.urgent.message}`)));
    for (const ct of r.urgent.contacts) console.log(c.red(`   ${ct.name}${ct.phone ? ` — ${ct.phone}` : ""}`));
  }
  const section = (title: string, body: string | string[], numbered = false) => {
    if (!body.length) return;
    console.log(c.cyan(c.bold(`\n${title}`)));
    if (typeof body === "string") console.log(`  ${body}`);
    else body.forEach((line, i) => console.log(`  ${numbered ? `${i + 1}.` : "•"} ${line}`));
  };
  section("Điều gì đang xảy ra", a.whatIsHappening);
  section("Vì sao quan trọng", a.whyItMatters);
  section("Bạn nên làm gì", a.whatToDo, true);
  section("Bằng chứng nên giữ", a.evidenceToKeep);
  section("Ai có thể giúp", a.whoCanHelp);

  if (r.sources.length) {
    console.log(c.bold("\nNguồn:"));
    for (const s of r.sources) {
      const cited = a.citations.includes(s.n);
      const line = `  [${s.n}] ${s.title}${s.url ? `  ${s.url}` : ""}`;
      console.log(cited ? `${line} ${c.green("✓ được trích")}` : c.dim(line));
    }
  }
  // Luôn báo bước lỗi, kể cả khi không bật --trace (vd rerank lỗi, sai API key)
  const failed = trace.filter((t) => !t.ok);
  if (opt.trace) printTrace(trace);
  else if (failed.length) {
    console.log(c.yellow(`\n! ${failed.length} bước gặp lỗi (thêm --trace để xem chi tiết):`));
    for (const t of failed) console.log(c.yellow(`   ${t.step}: ${String(typeof t.detail === "string" ? t.detail : JSON.stringify(t.detail)).slice(0, 150)}`));
  }
}

async function ask(message: string, profile: UserProfile) {
  const t0 = performance.now();
  const { response, trace } = await askAssistant(message, profile);
  return { response, trace, ms: Math.round(performance.now() - t0) };
}

// ---------- 5. Chạy bộ câu hỏi từ file ----------

interface Case {
  id?: string;
  message: string;
  profile?: Partial<Record<ProfileKey, string>>;
  expect?: { intent?: string; urgent?: boolean; source?: string; notInsufficient?: boolean };
}

function readCases(file: string): Case[] {
  const lines = readFileSync(file, "utf8").split(/\r?\n/).map((l) => l.trim()).filter((l) => l && !l.startsWith("#"));
  // .jsonl: mỗi dòng một JSON; file khác: mỗi dòng một câu hỏi
  return file.endsWith(".jsonl") ? lines.map((l) => JSON.parse(l) as Case) : lines.map((message) => ({ message }));
}

function checkExpect(e: Case["expect"], r: AssistantResponse): string[] {
  if (!e) return [];
  const fails: string[] = [];
  if (e.intent && r.intent !== e.intent) fails.push(`intent là ${r.intent}, cần ${e.intent}`);
  if (e.urgent !== undefined && r.urgent.show !== e.urgent) fails.push(`khối khẩn cấp ${r.urgent.show ? "có" : "không"}, cần ${e.urgent ? "có" : "không"}`);
  if (e.source) {
    const re = new RegExp(e.source, "i");
    const cited = r.sources.filter((s) => r.answer.citations.includes(s.n));
    if (!cited.some((s) => re.test(`${s.title} ${s.url ?? ""}`))) fails.push(`không có nguồn được trích khớp /${e.source}/`);
  }
  if (e.notInsufficient && r.answer.grounding === "insufficient") fails.push("trả lời 'chưa đủ nguồn'");
  return fails;
}

async function runFile(file: string, baseProfile: UserProfile) {
  const cases = readCases(file);
  console.log(c.bold(`Chạy ${cases.length} câu từ ${file}\n`));
  const results = [];
  let failed = 0;
  for (const [i, tc] of cases.entries()) {
    const id = tc.id ?? `#${i + 1}`;
    const profile = { ...baseProfile, ...normalizeProfile(tc.profile ?? {}) };
    try {
      const { response: r, trace, ms } = await ask(tc.message, profile);
      const fails = checkExpect(tc.expect, r);
      const stepErrors = trace.filter((t) => !t.ok).map((t) => t.step);
      if (fails.length) failed++;
      const mark = !tc.expect ? c.dim("·") : fails.length ? c.red("✗") : c.green("✓");
      console.log(`${mark} ${id.padEnd(5)} ${r.intent.padEnd(16)} ${r.risk.padEnd(6)} ${r.answer.grounding.padEnd(12)} ${String(ms).padStart(5)} ms  ${c.dim(tc.message.slice(0, 50))}`);
      for (const f of fails) console.log(c.red(`        → ${f}`));
      if (stepErrors.length) console.log(c.yellow(`        ! bước lỗi: ${stepErrors.join(", ")}`));
      results.push({ id, message: tc.message, profile, ms, intent: r.intent, risk: r.risk, mode: r.mode,
        grounding: r.answer.grounding, urgent: r.urgent.show, fails, stepErrors, response: r });
    } catch (e) {
      failed++;
      console.log(`${c.red("✗")} ${id.padEnd(5)} ${c.red(`LỖI: ${(e as Error).message}`)}`);
      results.push({ id, message: tc.message, error: (e as Error).message });
    }
  }
  const withExpect = cases.filter((tc) => tc.expect).length;
  const avg = Math.round(results.reduce((s, r) => s + ("ms" in r ? (r.ms as number) : 0), 0) / Math.max(results.length, 1));
  console.log(c.bold(`\nKết quả: ${withExpect - failed}/${withExpect} câu đạt kỳ vọng · thời gian trung bình ${avg} ms`));

  const dir = path.join("cli", "reports");
  mkdirSync(dir, { recursive: true });
  const out = path.join(dir, `ask-${new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19)}.json`);
  writeFileSync(out, JSON.stringify({ file, fake: isFakeMode(), results }, null, 2));
  console.log(c.dim(`Báo cáo chi tiết: ${out}`));
  return failed === 0;
}

// ---------- 6. Chế độ hỏi liên tục ----------

const HELP_INTERACTIVE = `Lệnh:
  /profile                     xem hồ sơ hiện tại
  /profile visa=student industry="Nail / Làm đẹp"   đặt hồ sơ (mã hoặc nhãn onboarding)
  /profile reset               xoá hồ sơ
  /trace   /json               bật/tắt nhật ký từng bước, in JSON
  /help    /quit`;

async function interactive(profile: UserProfile) {
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  console.log(c.bold("Trợ lý AI — chế độ hỏi liên tục") + c.dim("  (gõ /help để xem lệnh, /quit để thoát)"));
  console.log(c.dim(`Hồ sơ: ${describeProfile(profile)}`));
  rl.setPrompt(c.green("\nBạn: "));
  rl.prompt();
  // "for await" tự xếp hàng các dòng gõ/dán trong lúc trợ lý đang trả lời, không mất dòng nào
  for await (const raw of rl) {
    const line = raw.trim();
    if (line === "/quit" || line === "/exit") break;
    if (!line) { rl.prompt(); continue; }
    if (!process.stdin.isTTY) console.log(line); // đầu vào từ file/pipe: in lại câu để dễ đọc
    if (line === "/help") console.log(HELP_INTERACTIVE);
    else if (line === "/trace") { opt.trace = !opt.trace; console.log(`trace: ${opt.trace ? "bật" : "tắt"}`); }
    else if (line === "/json") { opt.json = !opt.json; console.log(`json: ${opt.json ? "bật" : "tắt"}`); }
    else if (line.startsWith("/profile")) {
      const rest = line.slice("/profile".length).trim();
      if (rest === "reset") profile = {};
      else if (rest) {
        const pairs = Object.fromEntries([...rest.matchAll(/(\w+)=("([^"]*)"|\S+)/g)].map((m) => [m[1], m[3] ?? m[2]]));
        profile = { ...profile, ...normalizeProfile(pairs) };
      }
      console.log(`Hồ sơ: ${describeProfile(profile)}`);
    } else {
      try {
        const { response, trace, ms } = await ask(line, profile);
        printResponse(response, trace, ms);
      } catch (e) {
        console.log(c.red(`LỖI: ${(e as Error).message}`));
      }
    }
    rl.prompt();
  }
  rl.close();
}

// ---------- 6b. Kiểm tra model: gọi thử từng model với key hiện tại ----------

async function checkModels() {
  const apiKey = process.env.GEMINI_API_KEY?.trim();
  if (!apiKey) {
    console.log(c.red("Thiếu GEMINI_API_KEY trong .env.local (chạy lệnh này ở thư mục gốc của app)"));
    return false;
  }
  const { GoogleGenAI } = await import("@google/genai");
  const ai = new GoogleGenAI({ apiKey });

  // 1. Danh sách Google công bố cho key này
  const listed: string[] = [];
  try {
    const pager = await ai.models.list({ config: { pageSize: 100 } });
    for await (const m of pager) {
      const name = (m.name ?? "").replace(/^models\//, "");
      const canGenerate = m.supportedActions?.includes("generateContent");
      // Chỉ lấy model văn bản dòng flash (rẻ, nhanh); bỏ ảnh, giọng nói, live...
      if (canGenerate && /flash/.test(name) && !/image|tts|audio|live|native|computer|robotics|thinking-exp/.test(name)) {
        listed.push(name);
      }
    }
  } catch (e) {
    console.log(c.red(`Không lấy được danh sách model: ${(e as Error).message.slice(0, 200)}`));
  }

  // 2. Gọi thử: danh sách có thể vẫn chứa model đã khoá với project mới
  const candidates = [...new Set([...NLU_MODELS, ...ANSWER_MODELS, ...listed])].slice(0, 14);
  console.log(c.bold(`Gọi thử ${candidates.length} model sinh văn bản (mỗi model một câu rất ngắn):\n`));
  const usable: string[] = [];
  for (const model of candidates) {
    const t0 = performance.now();
    try {
      await ai.models.generateContent({
        model,
        contents: "Reply with OK",
        config: { abortSignal: AbortSignal.timeout(20_000) },
      });
      usable.push(model);
      console.log(`  ${c.green("✓")} ${model.padEnd(36)} ${c.dim(`${Math.round(performance.now() - t0)} ms`)}`);
    } catch (e) {
      const msg = String((e as Error).message).replace(/\s+/g, " ");
      const reason = /no longer available/i.test(msg) ? "đã khoá với project mới"
        : /NOT_FOUND|404/.test(msg) ? "không tồn tại"
        : /429|quota|RESOURCE_EXHAUSTED/i.test(msg) ? "hết hạn mức (quota)"
        : /API_KEY_INVALID|API key not valid/.test(msg) ? "API key sai"
        : msg.slice(0, 80);
      console.log(`  ${c.red("✗")} ${model.padEnd(36)} ${c.dim(reason)}`);
    }
  }

  // 3. Embedding (phải là model đã dùng để tạo rag.db)
  try {
    const r = await ai.models.embedContent({
      model: EMBED_MODEL, contents: ["test"],
      config: { taskType: "RETRIEVAL_QUERY", outputDimensionality: EMBED_DIM },
    });
    const dim = r.embeddings?.[0]?.values?.length;
    console.log(`\n  ${dim === EMBED_DIM ? c.green("✓") : c.red("✗")} embedding ${EMBED_MODEL}: ${dim} chiều`);
  } catch (e) {
    console.log(`\n  ${c.red("✗")} embedding ${EMBED_MODEL}: ${(e as Error).message.slice(0, 120)}`);
  }

  if (!usable.length) {
    console.log(c.red("\nKhông model nào dùng được. Kiểm tra key, hạn mức, hoặc tạo key mới ở aistudio.google.com"));
    return false;
  }
  // 4. Gợi ý cấu hình: lite (rẻ, nhanh) cho NLU/rerank; flash thường trước, lite dự phòng cho câu trả lời
  const lite = usable.filter((m) => /lite/.test(m));
  const full = usable.filter((m) => !/lite/.test(m));
  const small = (lite.length ? lite : usable).slice(0, 2).join(",");
  const answer = [...full.slice(0, 1), ...lite.slice(0, 1)].join(",") || usable[0];
  console.log(c.bold("\nDán vào .env.local (rồi khởi động lại npm run dev):\n"));
  console.log(`AI_NLU_MODELS=${small}`);
  console.log(`AI_RERANK_MODELS=${small}`);
  console.log(`AI_ANSWER_MODELS=${answer}`);
  return true;
}

// ---------- 7. Chạy ----------

if (opt.help) {
  console.log(readFileSync(new URL(import.meta.url), "utf8").split("*/")[0].replace("/**", "").replace(/^ \* ?/gm, ""));
  process.exit(0);
}

if (opt.models) process.exit((await checkModels()) ? 0 : 1);

const profile = normalizeProfile(opt);
if (!opt.json) {
  console.log(c.dim(`rag.db: ${RAG_DB_PATH}${existsSync(RAG_DB_PATH) ? "" : "  (KHÔNG TÌM THẤY — chạy 09_publish.py bên rag-pipeline)"}`));
  console.log(c.dim(`Chế độ: ${isFakeMode() ? "giả (không gọi Gemini)" : process.env.GEMINI_API_KEY ? "Gemini" : "Gemini — nhưng THIẾU GEMINI_API_KEY"} · hồ sơ: ${describeProfile(profile)}`));
}

if (opt.file) {
  process.exit((await runFile(opt.file, profile)) ? 0 : 1);
} else if (positionals.length) {
  const { response, trace, ms } = await ask(positionals.join(" "), profile);
  printResponse(response, trace, ms);
} else {
  await interactive(profile);
}
