# Repository Guidelines

## Project Structure & Module Organization

This repository implements an advisory review workflow for GovCon oral-proposal packages. `web/` is the Next.js application for authentication, uploads, analysis status, and reports. Its application routes live in `web/src/app/`, shared server code is in `web/src/lib/`, and the Drizzle schema and migrations are in `web/src/db/` and `web/drizzle/`. `worker/` is the Python job-processing pipeline; package code is under `worker/src/worker/` and tests are in `worker/tests/`. Product goals, specs, and implementation plans are in `GOALS.md` and `docs/`.

## Build, Test, and Development Commands

Start local Postgres services with:

```sh
docker compose -f docker-compose.dev.yml up -d
```

In `web/`, run `npm install`, copy `.env.example` to `.env.local`, then use `npm run dev` for local development, `npm run build` for a production build, `npm run lint` for ESLint, and `npm test` for Vitest. Run `npm run db:migrate` after migration changes; use `npm run db:generate` to create Drizzle migrations.

In `worker/`, activate the Python 3.12+ virtual environment, then run `pytest` for the suite. Run the worker locally with `DATABASE_URL=... python -m worker.main`.

## Coding Style & Naming Conventions

Follow the surrounding code and keep changes narrowly scoped. TypeScript uses the project ESLint configuration and standard Next.js conventions: components in PascalCase, utilities in camelCase, and route handlers in `src/app/api/**/route.ts`. Python uses four-space indentation, `snake_case` functions and modules, and `PascalCase` classes. Keep database migrations ordered and named by the generated Drizzle convention.

## Testing Guidelines

Add or update tests with behavior changes. Web tests use Vitest and sit beside the code as `*.test.ts` (for example, `src/lib/validation.test.ts`). Worker tests use pytest and follow `worker/tests/test_<module>.py`. Reuse existing fixtures in `worker/tests/fixtures/` for document-processing cases. Run the targeted suite first, then the relevant full suite before opening a pull request.

## Commit & Pull Request Guidelines

Use Conventional Commit-style messages consistent with history: `feat(web): ...`, `fix(worker): ...`, `test(worker): ...`, `docs: ...`, or `chore: ...`. Keep each commit focused. Pull requests should state the user-facing or pipeline impact, list tests run, link the relevant issue or plan when applicable, and include screenshots for visible web UI changes. Do not commit `.env.local`, credentials, or production tokens.
