# Claude Code Project Instructions

Read and follow all rules in [AGENTS.md](./AGENTS.md) — that is the canonical quality spec.

## Additional Claude-specific guidance

- When modifying existing functions, check if the result exceeds 50 lines. If so, split before committing.
- After any code change, run `python scripts/quality_gate.py --check-functions` to verify.
- Prefer editing existing files over creating new ones.
- When adding features to the web app, implement them as Agent tools in `web/apps/web/src/lib/chat-agent.ts`, not as new routes.
- Streamlit has been fully retired from `main`. Do not add or revive Streamlit code; historical MVP code lives on `release/streamlit`, with product architecture and screenshots in [docs/STREAMLIT_MVP_ARCHITECTURE.md](docs/STREAMLIT_MVP_ARCHITECTURE.md).
- The legacy function whitelist (`.metrics/func_whitelist.json`) exists for historical debt. When you touch a whitelisted function, try to bring it under the 50-line limit — but don't refactor unrelated code.
