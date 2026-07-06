import path from "node:path";
import { defineConfig } from "vitest/config";

// DB-backed tests run against a dedicated test database (never the dev DB),
// matching the port convention already used by the worker's pytest suite
// (postgres on 5434 = dev, 5435 = test).
const TEST_DATABASE_URL =
  process.env.TEST_DATABASE_URL ??
  "postgres://postgres:dev@localhost:5435/agentic_review_test";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    env: {
      DATABASE_URL: TEST_DATABASE_URL,
    },
    globalSetup: ["./src/test/global-setup.ts"],
  },
});
