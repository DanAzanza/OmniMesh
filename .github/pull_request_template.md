## 📋 Description of Changes

A clear and concise summary of what this pull request introduces or fixes.

---

## 🎯 Motivation & Context

- Why is this change required? What problem does it solve?
- If this fixes an open issue, link it here (e.g. `Fixes #123`).

---

## 🛠️ Type of Change

- [ ] 🐛 Bug fix (non-breaking change which fixes an issue)
- [ ] ✨ New feature (non-breaking change adding pipeline/operator functionality)
- [ ] ⚡ Performance optimization (BMesh speed, reduction solver, memory hygiene)
- [ ] 🎮 Engine exporter update (MSFS 2024 / UE5 / Unity 6 / Godot 4)
- [ ] 🧹 Refactoring or code quality enhancement
- [ ] 📖 Documentation update

---

## ✅ Verification & Quality Checklist

Before opening this PR, confirm you have completed the following steps:

- [ ] Code strictly follows English naming and documentation standards.
- [ ] `python -m ruff check .` passes with **0 errors**.
- [ ] `python -m ruff format --check .` passes with **0 errors**.
- [ ] `python -m pyright .` passes with **0 errors / 0 warnings**.
- [ ] `python -m pytest -v` passes **100% of test suites**.
- [ ] Tested manually inside Blender 4.2+ / 5.2 LTS (if UI or operators were modified).
