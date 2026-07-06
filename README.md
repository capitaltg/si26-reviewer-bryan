# AI Proposal Review Board

Advisory-only review of GovCon oral-proposal packages (deck + narration script)
against the actual solicitation. See `GOALS.md` and
`docs/superpowers/specs/2026-07-02-ai-proposal-review-board-design.md`.

- `web/` — Next.js app (Vercel): auth, uploads, status, report
- `worker/` — Python pipeline worker (Railway): claims jobs from Postgres
- `docs/` — specs and plans

## Local dev

1. `docker compose -f docker-compose.dev.yml up -d` (Postgres on 5434, test DB on 5435)
2. `cd web && cp .env.example .env.local && npm install && npm run db:migrate && npm run dev`
3. `cd worker && source .venv/bin/activate && DATABASE_URL=postgres://postgres:dev@localhost:5434/agentic_review python -m worker.main`
