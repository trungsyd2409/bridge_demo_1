import { GoogleGenAI } from "@google/genai";
import fs from "fs";
import path from "path";

const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY });

type EmbeddedChunk = {
    source: string;
    chunk_id: number;
    text: string;
    embedding: number[];
};

// Load embeddings.json 1 lần, giữ trong bộ nhớ (không đọc lại file mỗi lần có câu hỏi)
let cachedChunks: EmbeddedChunk[] | null = null;

function loadEmbeddings(): EmbeddedChunk[] {
    if (cachedChunks) return cachedChunks;
    const filePath = path.join(process.cwd(), "src/data/embeddings.json");
    const raw = fs.readFileSync(filePath, "utf-8");
    cachedChunks = JSON.parse(raw);
    return cachedChunks!;
}

function cosineSimilarity(a: number[], b: number[]): number {
    let dot = 0, normA = 0, normB = 0;
    for (let i = 0; i < a.length; i++) {
        dot += a[i] * b[i];
        normA += a[i] * a[i];
        normB += b[i] * b[i];
    }
    return dot / (Math.sqrt(normA) * Math.sqrt(normB));
}

async function embedQuery(text: string): Promise<number[]> {
    const result = await ai.models.embedContent({
        model: "gemini-embedding-001",
        contents: text,
        config: {
            taskType: "RETRIEVAL_QUERY",
            outputDimensionality: 768,
        },
    });
    // Lưu ý: nếu dòng dưới báo lỗi undefined, console.log(result) ra để xem đúng cấu trúc trả về,
    // vì SDK có thể trả object hơi khác tuỳ phiên bản.
    return result.embeddings?.[0]?.values ?? [];
}

export async function retrieveContext(question: string, topK = 3): Promise<string[]> {
    try {
        const chunks = loadEmbeddings();
        const queryVector = await embedQuery(question);

        const scored = chunks.map((chunk) => ({
            text: chunk.text,
            score: cosineSimilarity(queryVector, chunk.embedding),
        }));

        scored.sort((a, b) => b.score - a.score);
        return scored.slice(0, topK).map((s) => s.text);
    } catch (err) {
        console.error("RAG retrieval lỗi, bỏ qua context bổ sung:", err);
        return []; // trả về rỗng thay vì crash — askAssistantSmart vẫn chạy được với knowledgeBase cũ
    }
}