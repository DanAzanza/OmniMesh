# OrdinFlow Domain & Runtime Knowledge Base

> **Rule**: This repository knowledge base serves strictly as persistent memory for **non-obvious runtime quirks, hardware/model constraints, and hidden system behaviors** that cannot be inferred from reading source code, function signatures, or docstrings alone. Do NOT document standard component mappings, obvious file listings, or generic code patterns here.


## 1. Verification Commands & Quality Gates

* **Iterative Development (Code changes only)**:
  ```bash
  python -m pytest -q
  ```
  *(Run ONLY when `.py`/`.js` code changed. Never run Ruff or Pyright during iterative steps).*

* **Pre-Commit Quality Gate (Triggered strictly on explicit user commit request)**:
  ```bash
  python scripts/verify_ci.py
  ```
  *(Runs Ruff linter, Pyright type checker on `core/` and `routes/`, and full test suite).*

---

## 2. Specialized Multi-Agent Quality Subagents

* **`plan_critic` ("Grill Me" Sparring Panel)**: Multi-perspective architectural reviewer before writing implementation plans. Actively attacks assumptions, validates against real codebase APIs, and enforces KISS/YAGNI.
* **`pre_commit_auditor` ("Grill Me" Code & Goal Auditor)**: Adversarial auditor before commit approval. Scrutinizes `git diff` against Plan Fidelity (no cut corners) and `AGENTS.md` standards (zero placeholders, cross-platform guards, SRP limits).
