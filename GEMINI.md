# Project Architecture & Workflow Conventions

## 1. Frontend Architecture
*   **React (`web/`) is the production web surface.** New user-facing capabilities should be implemented in the Agent/chat experience rather than new standalone routes.
*   **Streamlit is fully retired from `main`.** Do not add, restore, or maintain Streamlit runtime code. Historical MVP code is preserved on `release/streamlit`; product architecture and screenshots are archived in [docs/STREAMLIT_MVP_ARCHITECTURE.md](docs/STREAMLIT_MVP_ARCHITECTURE.md).
*   **Agent Rule:** Route product work through CF Pages, CLI, MCP, or GitHub Actions. Do not use Streamlit as a grey-release path.

## 2. Documentation Structure
*   **Wiki Visibility:** The `wiki_repo_new/` directory is **intentionally kept hidden** (ignored via `.gitignore`).
*   **Agent Rule:** Do NOT suggest removing `wiki_repo_new/` from `.gitignore` or complain about its invisibility in the repository. Do not suggest merging its contents into `docs/` unless explicitly requested by the user.
