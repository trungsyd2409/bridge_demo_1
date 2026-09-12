interface Bucket {
    count: number;
    windowStart: number;
}

// Map lưu trong bộ nhớ RAM của server — mất khi restart server, chấp nhận được
// vì mục đích chỉ là chặn spam ngắn hạn, không cần bền vững qua DB.
const buckets = new Map<string, Bucket>();

/**
 * Fixed-window rate limiter đơn giản.
 * key: định danh duy nhất (ở đây dùng userId), limit: số request tối đa trong 1 khung thời gian,
 * windowMs: độ dài khung thời gian tính bằng mili-giây.
 */
export function checkRateLimit(
    key: string,
    limit: number,
    windowMs: number
): { allowed: boolean; retryAfterMs: number } {
    const now = Date.now();
    const bucket = buckets.get(key);

    if (!bucket || now - bucket.windowStart >= windowMs) {
        // Chưa có bucket, hoặc khung thời gian cũ đã hết -> mở khung mới
        buckets.set(key, { count: 1, windowStart: now });
        return { allowed: true, retryAfterMs: 0 };
    }

    if (bucket.count < limit) {
        bucket.count += 1;
        return { allowed: true, retryAfterMs: 0 };
    }

    return { allowed: false, retryAfterMs: windowMs - (now - bucket.windowStart) };
}