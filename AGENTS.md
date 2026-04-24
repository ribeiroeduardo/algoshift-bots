## Cursor Cloud specific instructions

### Overview

AlgoShift is a React + TypeScript + Vite SPA for crypto traders. Backend is hosted Supabase (no local DB needed). See `CLAUDE.md` for full project description and coding guidelines.

### Running the app

- **Dev server**: `npm run dev` — serves on port 8080
- **Tests**: `npm test` (Vitest, 57 tests across 12 files)
- **Lint**: `npm run lint` (ESLint 9; pre-existing lint errors in the codebase — do not attempt to fix unless asked)
- **Build**: `npm run build`
- **Full verify**: `npm run verify` (TypeScript check + tests + build)

### Auth and Supabase

When `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` are set, the app shows a Google OAuth login screen. Without credentials to log in, most features are inaccessible. When these values are empty/unset, the app bypasses authentication and runs in offline/demo mode — all Supabase persistence functions return early with no-ops.

For UI testing without a real Supabase account, clear these env vars to use offline mode. The `.env` file is gitignored; secrets are injected via Cursor Cloud secrets (`VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`).

### Environment variables

The `.env` file is auto-generated at setup from secrets. See `.env.example` for all available variables. Key secrets: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` (required for auth), `VITE_OPENROUTER_API_KEY` (required for AI mentor).

### Non-obvious caveats

- The `eslint` config uses ESLint 9 flat config. The codebase has ~26 pre-existing lint errors (mostly `@typescript-eslint/no-explicit-any`). These are not blocking for development.
- Vite dev server binds to `::` (all interfaces) on port 8080, configured in `vite.config.ts`.
- HMR overlay is disabled in vite config (`hmr.overlay: false`).
- The `bun.lockb` file exists alongside `package-lock.json`, but `npm` is the standard package manager per project conventions.

### Supabase MCP (obrigatório para o agente)

- **Nunca** pedir ao utilizador para fazer manualmente o que o **Supabase MCP** possa fazer (deploy de Edge Functions, SQL/migrations quando aplicável, consultas, etc.). O agente deve **executar** via MCP e só envolver o utilizador se a ferramenta falhar ou faltar permissão/credencial que só o humano pode fornecer.
- O mesmo para tarefas repetíveis de backend Supabase: **tentar MCP primeiro**, não instruções do tipo “faz deploy tu”.

### Supabase Edge Functions (deploy)

- Ao **terminar** alterações em `supabase/functions/<nome>/`, **fazer deploy** para o projeto em produção (`project_id` em `supabase/config.toml`).
- **Preferir** o **Supabase MCP** (`deploy_edge_function`): incluir `index.ts`, dependências locais (ex.: `mentor-reply-edge.ts`), `entrypoint_path`, `verify_jwt` alinhado a `config.toml`.
- Se o payload for **demasiado grande** para o MCP, usar **CLI com API** (sem Docker):  
  `npx supabase functions deploy <nome> --project-ref tyopcloyydlrjwrvrtfn --use-api`
- Remover ficheiros temporários de deploy (ex.: `.mcp-deploy-diario-chat.json`) e não commitar segredos.
