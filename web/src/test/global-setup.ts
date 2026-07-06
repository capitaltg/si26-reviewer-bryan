// Vitest globalSetup: resets the dedicated test database (never the dev DB)
// and applies every Drizzle migration in order, mirroring the pattern already
// established for the worker's pytest suite (worker/tests/conftest.py).
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { Client } from "pg";

export const TEST_DATABASE_URL =
  process.env.TEST_DATABASE_URL ??
  "postgres://postgres:dev@localhost:5435/agentic_review_test";

const MIGRATIONS_DIR = path.resolve(__dirname, "../../drizzle");

export default async function setup() {
  const client = new Client({ connectionString: TEST_DATABASE_URL });
  await client.connect();
  try {
    await client.query("DROP SCHEMA public CASCADE");
    await client.query("CREATE SCHEMA public");
    const files = readdirSync(MIGRATIONS_DIR)
      .filter((f) => f.endsWith(".sql"))
      .sort();
    for (const file of files) {
      const sql = readFileSync(path.join(MIGRATIONS_DIR, file), "utf8");
      for (const statement of sql.split("--> statement-breakpoint")) {
        const trimmed = statement.trim();
        if (trimmed) {
          await client.query(trimmed);
        }
      }
    }
  } finally {
    await client.end();
  }
}
