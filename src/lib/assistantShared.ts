import { ProblemTag } from "@/data/supportOrgs";

export interface AssistantResponse {
    topic: string;
    whatMightBeHappening: string;
    whyItMatters: string;
    whatYouCanDo: string[];
    evidenceToKeep: string[];
    helpTags: ProblemTag[];
    // ---- Trường mới từ pipeline RAG (tuỳ chọn: tin nhắn cũ trong lịch sử không có) ----
    whoCanHelp?: string[];
    sources?: { n: number; title: string; source: string; url?: string; kind: string; cited: boolean }[];
    urgent?: { message: string; contacts: { name: string; phone?: string; url?: string; note: string }[] };
    grounding?: "grounded" | "partial" | "insufficient";
    engine?: "rag-gemini" | "rag-fallback" | "legacy";
}

export interface ChatTurn {
    role: "user" | "assistant";
    content: string;
}

export const DEMO_DISCLAIMER =
    "Trợ lý AI có thể dùng mô hình AI thật (Gemini) khi có kết nối, hoặc câu trả lời dựng sẵn khi cần — chỉ mang tính tham khảo, không phải tư vấn pháp lý.";