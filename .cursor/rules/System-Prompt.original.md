---
description: 
alwaysApply: true
---

Always use /caveman ultra

Always reply in English, no matter the language of the message I sent.
Whenever database SQL commands or edge functions are involved, use the Supabase MCP.
Never ask the user to manually perform what you can do yourself with the Supabase MCP (Edge Function deployment, supported project operations, etc.); execute via MCP and only involve the human if the tool fails or requires something only they can provide.
Whenever GitHub is involved, use the GitHub MCP.
All features must reside in their own folder and must be self-contained regarding code to prevent changes in one place from breaking something seemingly disconnected from the modified context.
Whenever working with UI, customize the scrollbar according to the page style; never use the browser's native scrollbar.

Worktrees — Mandatory Setup
This project uses git worktrees to allow multiple agents to code in parallel without conflicts. Each agent receives an isolated worktree with its own branch.

Problem: Worktrees do not inherit gitignored files (like .env). Without .env, the Supabase client is null and nothing works.

Upon receiving or creating a worktree, immediately execute:

Bash
bash scripts/setup-worktree.sh
This creates symlinks for .env (and .env.local if it exists) from the main repo to the worktree. This only needs to be done once per worktree.

GitHub (Workflow)
Branches: Work on a dedicated branch (feature/…, fix/…, or a short descriptive name). Avoid direct commits to main when the repository uses PRs.

Commits: Clear messages in the imperative mood (e.g., “Add date filter to performance”); one subject per commit whenever possible; reference issue/Linear if it exists (#123).

Push: git push the current branch; do not use git push --force on shared branches or main unless explicitly agreed upon (e.g., rebase after review).

Pull Request: Describe what changed, why, and how to validate (test commands, manual UI steps); attach screenshots for visual changes; tag reviewers when applicable.

CI and Testing: Do not merge with a red pipeline; run npm test / tsc locally before requesting a merge when changes involve critical code.

Code Review: Respond to comments (or mark as resolved after fixing); do not implement blindly — ask questions if feedback is ambiguous or risky; keep the PR focused (avoid mixing large refactors with features). Use the sub-agent /code-reviewer.

After Merge: Delete the remote branch if the repo policy allows; update the local branch (git pull on base).

Stack
Frontend: React + TypeScript + Vite + Tailwind CSS

Backend: Supabase (Postgres + Auth + Storage + Edge Functions)

Testing: Vitest

Market Data: Bybit public Linear/Perp USDT API (public, no authentication for klines and tickers)

AI: OpenRouter (user-configurable models)

About the Project
AlgoShift is a web application for traders that centralizes daily operations in one place: reflection and logging (journaling), AI mentor chat with market context, performance analysis from imported trades, metrics and curve visualization, and market data (Bybit linear klines and client-side calculated SMC indicators). The backend is Supabase (auth, data, and functions); the AI layer uses OpenRouter with models chosen by the user. The goal is to reduce fragmentation between tools and keep the workflow consistent with preferences saved in Settings.

Features (Overview)
The dashboard groups routes and the main tab model of the authenticated area (/cockpit, /analytics, /performance, /indicadores, /sessoes, /settings/...), ensuring navigation and URLs are centralized and predictable.

The auth feature handles the app entry flow: login screen, route protection, and Supabase session callback, ensuring only authenticated users access the rest of the product.

The cockpit is the operational core: daily journal by date (text and images, timeline, and calendar), AI mentor chat linked to the selected day, and integration with charts and market data aligned with mentor preferences; this is where the trader combines reflection, market context, and assisted conversation. The /indicadores route (Indicators tab; redirect from /smc-teste) reuses the market and SMC stack in a dedicated screen to explore and validate indicators without going through the journal flow.

Analytics presents aggregated statistics and visualizations regarding the trade list and trading definitions: equity curves, win rate, average profit per trade, W/L ratio, time slots, and metric cards, based on trade-utils and shared types.

Performance focuses on the performance table by calendar (day, week, month, year), history import (CSV / TradingView), and inspection of trade sets, serving as a detailed operational "ledger" compared to the more aggregated Analytics panel.

market-data is the feature dedicated to public Bybit linear data (klines, tickers) and the SMC indicator engine (structure, liquidity, FVG, order blocks, etc.), exposed for reuse; the cockpit imports this feature for modals and market flows without duplicating logic.

settings concentrates Configurations into sections (Trading, AI Mentor, SMC Indicators, APIs): account and risk parameters, mentor model and context, SMC tuning, and integration status.

sessions reserves the “Sessions” tab for future evolution (AI-generated period summaries); currently functions as a product placeholder with a user-oriented message.

Folder and File Organization for Features
Each product domain lives in src/features//, with subfolders by responsibility (e.g., components/, hooks/, lib/) when it makes sense; a single pattern is not mandatory for all, but it must be consistent within the same feature.

Code shared by two or more features does not stay in features/; it belongs in src/lib/ (types, trade utilities, Supabase client, etc.). Only create a file in src/lib/ if you have a real use case in more than one feature.

src/shared/ stores cross-cutting UI and layout (shell components, tooltips, common visual themes) that are not specific "business rules" of an isolated feature.

Tests that exercise a feature can live in src/test/ with a name aligned to the tested module, or alongside the feature if the project moves to collocation — currently, the repository uses src/test/ for several cases.

The market-data feature is the only module in src/features/ that another feature can import via a direct path: cockpit can import @/features/market-data. Avoid importing features/X from features/Y for any other pair; this enforces clear dependencies and avoids network coupling.

Self-Contained Feature Development
Clear Boundary: A feature should be readable and modifiable predominantly within its own folder, using @/lib and @/shared as "downward" dependencies, without depending on internal details of another feature (except for the explicit cockpit → market-data exception).

Minimal Public API: Export only what is necessary (e.g., an index.ts at the feature root or well-named modules) so that routes and pages import stable points; keep hooks and helpers "private" (not exported) when they are not part of the feature's contract.

Shared Types and Business Rules: These stay in src/lib/trade-types, trade-utils, etc., instead of duplicating types between features.

Side Effects and Data: Prefer passing data and callbacks via props or hooks declared within the feature itself; avoid reading global state or "knowing" how another tab persists data, except for explicit contracts in lib/.

Coordinated Changes: When a change requires touching two features, question whether part of the code should be moved up to src/lib/ (if it becomes cross-cutting) or if the dependency should be inverted (who should depend on whom) to keep each feature testable and reviewable in isolation.
