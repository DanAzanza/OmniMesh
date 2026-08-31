# Contributing to OmniMesh

Thank you for your interest in contributing to **OmniMesh**! OmniMesh is developed and maintained by **Daniel** ([@DanAzanza](https://github.com/DanAzanza)). Bug reports, feature suggestions, documentation enhancements, and pull requests are very welcome.

---

## 📜 Code of Conduct

This project and everyone participating in it is governed by the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

---

## 🛠️ Development Setup

1. **Fork and Clone the Repository:**
   ```bash
   git clone https://github.com/<your-username>/OmniMesh.git
   cd OmniMesh
   ```

2. **Create and Activate a Virtual Environment:**
   ```bash
   python -m venv venv
   # On Linux/macOS:
   source venv/bin/activate
   # On Windows:
   venv\Scripts\activate
   ```

3. **Install Development & Quality Tools:**
   ```bash
   python -m pip install --upgrade pip
   pip install ruff pyright fake-bpy-module-latest pytest
   ```

---

## 🚦 Local Quality Gates & CI Pre-Flight Checks

Before submitting a pull request, ensure all local verification checks pass with **0 errors and 0 warnings**:

1. **Linting & Code Style:**
   ```bash
   python -m ruff check .
   python -m ruff format --check .
   ```

2. **Static Type Analysis:**
   ```bash
   python -m pyright .
   ```

3. **Automated Unit Tests:**
   ```bash
   python -m pytest -v
   ```

---

## 📐 Coding Standards & Guidelines

* **Strict English Codebase:** All Python code, variable names, functions, classes, docstrings, and inline comments must be written in English.
* **Type Hints:** Use explicit typing throughout (`from typing import ...`, Type Annotations).
* **Blender & BMesh Hygiene:** Always free BMesh instances (`bm.free()`) and avoid modifying Blender RNA/DNA properties inside draw callbacks.
* **Cross-Platform OS Compatibility:** Use `pathlib.Path` or `os.path` for path handling. Never hardcode platform-specific absolute paths.
* **Zero Placeholders:** Never submit code containing placeholders, summaries, or truncation comments (`# TODO: implement later`, `...`).

---

## 📝 Git Commit Guidelines

Commit messages must follow this concise format:

* **Subject Line:**
  * Maximum **50 characters**.
  * Start with a capital letter.
  * Do not end with a period.
  * Use the **imperative mood** (e.g. `Add bone pruning tolerance test` instead of `Added tests`).
* **Body:**
  * Explain the **reason** for the change and any key context.
  * Keep it to 1–2 short sentences.

Example:
```
Add bone pruning tolerance test

Verify bottom-up leaf bone weight collapse when projected screen diameter falls below 1.5px.
```

---

## 🔄 Pull Request Workflow

1. Create a feature branch: `git checkout -b feature/my-new-feature`
2. Commit your changes following the commit message guidelines.
3. Run and verify all local CI checks (`ruff`, `pyright`, `pytest`).
4. Push your branch to GitHub: `git push origin feature/my-new-feature`
5. Open a Pull Request against the `main` branch with a clear description of your changes.

Thank you for contributing to OmniMesh!
