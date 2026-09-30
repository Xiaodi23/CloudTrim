# Bilingual README Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish matching Chinese and English LasTool README files with visible language switching and direct release downloads.

**Architecture:** Keep one complete document per language. `README.md` is the default Chinese landing page and `README_EN.md` is its English counterpart; both use the same links, facts, commands, tables, and section order.

**Tech Stack:** GitHub-flavored Markdown, PowerShell verification, Python unittest, Git.

---

### Task 1: Create the Chinese landing page

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace the English landing page with natural Simplified Chinese**

Use this exact section order: language switch, project title and summary, badges, portable download callout, features, portable use, source use, output table, build, tests, limitations, privacy, license. Link the language switch to `README.md` and `README_EN.md`; link the download to `https://github.com/Xiaodi23/CloudTrim/releases/download/v0.1.0/LasTool-windows-x64.zip` and the release page to `https://github.com/Xiaodi23/CloudTrim/releases/latest`.

- [ ] **Step 2: Review the Chinese prose for natural technical writing**

Remove promotional phrasing, mechanical one-to-one translation, excessive bold text, repetitive sentence shapes, and generic conclusions. Keep commands and technical names unchanged.

### Task 2: Create the matching English document

**Files:**
- Create: `README_EN.md`

- [ ] **Step 1: Preserve the current technical content in the English file**

Use the same section order, badges, direct download URL, source commands, output table, build instructions, limitations, privacy statement, and license link as the Chinese file.

- [ ] **Step 2: Add reciprocal language navigation**

The first content line in both files must be:

```markdown
[简体中文](README.md) | [English](README_EN.md)
```

### Task 3: Verify and publish

**Files:**
- Verify: `README.md`
- Verify: `README_EN.md`

- [ ] **Step 1: Check structural parity and required URLs**

Run a PowerShell check that reads both files, asserts the reciprocal language links, confirms the `v0.1.0` direct-download URL appears the same nonzero number of times in each file, and confirms each document contains the same number of level-two headings.

Expected: `README parity checks: OK`.

- [ ] **Step 2: Run project verification**

Run:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q main.py src tests
git diff --check
```

Expected: 15 tests pass, compilation exits successfully, and Git reports no whitespace errors.

- [ ] **Step 3: Commit and push**

Run:

```powershell
git add README.md README_EN.md docs/superpowers/plans/2026-08-12-bilingual-readme.md
git commit -m "docs: add Chinese and English README versions"
git push origin main
```

Expected: `main` advances on GitHub and the working tree is clean.

- [ ] **Step 4: Confirm remote state**

Compare `git rev-parse HEAD` with `git ls-remote origin refs/heads/main`, then request the raw GitHub URLs for both README files and confirm HTTP 200 responses.
