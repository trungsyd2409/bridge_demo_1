import { DatabaseSync } from "node:sqlite";
import path from "node:path";
import fs from "node:fs";
import { randomUUID } from "node:crypto";

const DB_DIR = path.join(process.cwd(), "data");
const DB_PATH = path.join(DB_DIR, "app.db");

declare global {
  // eslint-disable-next-line no-var
  var __uavsDb: DatabaseSync | undefined;
}

function createDb(): DatabaseSync {
  if (!fs.existsSync(DB_DIR)) fs.mkdirSync(DB_DIR, { recursive: true });
  const db = new DatabaseSync(DB_PATH);
  db.exec("PRAGMA journal_mode = WAL;");
  db.exec("PRAGMA foreign_keys = ON;");

  db.exec(`
    CREATE TABLE IF NOT EXISTS users (
      id TEXT PRIMARY KEY,
      email TEXT UNIQUE NOT NULL,
      name TEXT NOT NULL,
      password_hash TEXT NOT NULL,
      created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS profiles (
      user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
      goal TEXT,
      experience TEXT,
      visa TEXT,
      industry TEXT,
      employment TEXT,
      onboarding_complete INTEGER NOT NULL DEFAULT 0,
      updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS job_checks (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      industry TEXT NOT NULL,
      role TEXT,
      employment_type TEXT NOT NULL,
      pay_amount REAL NOT NULL,
      pay_unit TEXT NOT NULL,
      hours_per_week REAL,
      working_days TEXT,
      payment_method TEXT NOT NULL,
      visa TEXT NOT NULL,
      has_payslips TEXT,
      risk_level TEXT NOT NULL,
      risk_score INTEGER NOT NULL,
      risk_reasons TEXT NOT NULL,
      created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS lesson_progress (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      lesson_id TEXT NOT NULL,
      completed INTEGER NOT NULL DEFAULT 0,
      score INTEGER NOT NULL DEFAULT 0,
      completed_at TEXT,
      UNIQUE(user_id, lesson_id)
    );

    CREATE TABLE IF NOT EXISTS evidence_items (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      type TEXT NOT NULL,
      title TEXT NOT NULL,
      note TEXT,
      file_name TEXT,
      mime_type TEXT,
      file_data TEXT,
      created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS ai_messages (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      role TEXT NOT NULL,
      content TEXT NOT NULL,
      topic_tag TEXT,
      created_at TEXT NOT NULL
    );
  `);

  return db;
}

export function getDb(): DatabaseSync {
  if (!globalThis.__uavsDb) {
    globalThis.__uavsDb = createDb();
  }
  return globalThis.__uavsDb;
}

export function newId(): string {
  return randomUUID();
}

export function nowIso(): string {
  return new Date().toISOString();
}
