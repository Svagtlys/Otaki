---
name: create-work-item
description: Use when creating a GitHub issue for the Otaki project — new features, bugs, chores, or documentation. Triggers when the model discovers a problem during coding that should be tracked separately, or the user asks to file an issue, create a ticket, or log a bug.
---

# Create Work Item

## Overview

Create a GitHub issue following Otaki's naming convention, labeling, milestone assignment, and minimal-body rules. Issues must be actionable for future implementation or debugging.

**Core principle:** An issue is a work specification, not a conversation. Include only what's needed to recreate the work.

## When to Use

- User reports a bug and asks to "file an issue" or "create a ticket"
- User proposes a feature and wants it tracked
- You discover a problem during coding that should be tracked separately
- User says "log this", "create an issue", "open a ticket"

**Do NOT use when:** The work is trivial enough to commit directly (typos, one-line fixes).

## Pre-creation Checks

### 1. Check for Similar Open Issues

Before creating a new issue, search for existing open GitHub issues that cover the same problem:

```bash
gh issue list --repo Svagtlys/Otaki --state open --search "<keyword1>|<keyword2>"
```

Search using keywords from the error message, affected module, or function names. If a matching open issue exists, reference it instead of creating a duplicate.

### 2. Verify Branch is Up to Date with Develop

Check that the current branch is based on (or rebased onto) the latest `develop`:

```bash
git fetch origin develop
git merge-base HEAD origin/develop
git rev-parse origin/develop
```

If the merge-base does not match `origin/develop`, the branch is behind. Ask the user to rebase:

```bash
git rebase origin/develop
```

After rebasing, verify the bug still exists (or the feature is still needed) — it may have been fixed or addressed in a merged PR.

## Issue Title Convention

**Format:** `<type>(<area>): <short description>`

| Type | When | Example |
|------|------|---------|
| `bug` | Something broken | `bug(file-relocator): empty manga_title resolves to entire source folder` |
| `feat` | New feature | `feat(ui): source-manga pin management on comic detail page` |
| `fix` | UI/code fix (not a bug report) | `fix(ui): show 'upgrade queued' when reprocess triggers upgrade` |
| `ci` | CI/CD pipeline | `ci: investigate arm64 frontend build failure` |
| `chore` | Maintenance, deps | `chore: update pytest to 8.3` |
| `docs` | Documentation | `docs: add API endpoint for chapter reprocess` |

**Area** — the module or component affected: `ui`, `file-relocator`, `source_selector`, `db`, `cadence`, `scheduler`, `auth`, `reprocess`, `search`, `library`, etc. Omit area for cross-cutting concerns (`ci:`, `chore:`).

**Description** — imperative, under 60 characters. No period at end.

## Labels

Apply exactly ONE primary label:

| Label | Issue type |
|-------|-----------|
| `bug` | Something isn't working |
| `enhancement` | New feature or request |
| `documentation` | Docs only |

Add secondary labels when applicable: `good first issue`, `help wanted`.

## Milestone

Assign to the most appropriate open milestone. Check available milestones first:

```bash
gh milestone list
```

Install the gh cli milestone extension via:
```bash
gh extension install valeriobelli/gh-milestone
```

## Issue Body

### Bug Reports

```markdown
## Description

[What happens vs what should happen — 2-3 sentences max]

## Root Cause

[If known: which function, what condition triggers it. If unknown: "Investigate needed"]

## Reproduction

1. [Step 1]
2. [Step 2]
3. [Observed result]

## Fix

[If known: suggested approach. If unknown: omit this section]
```

### Feature Requests

```markdown
## Description

[What the feature does — 2-3 sentences]

## Why

[User problem this solves — not "it would be nice"]

## Scope

- [ ] [Backend task if applicable]
- [ ] [Frontend task if applicable]
- [ ] [Tests]
```

## Creation Command

```bash
gh issue create \
  --repo Svagtlys/Otaki \
  --title "<type>(<area>): <description>" \
  --label "<label>" \
  --milestone "<milestone-title>" \
  --body "$(cat issue-body.md)"
```

## Add to Project

After creation, add the issue to the Otaki Milestone Tracker (project `6`):

```bash
gh project item-add 6 --owner Svagtlys --url "<issue-url>"
```

The issue URL is output by `gh issue create` (e.g., `https://github.com/Svagtlys/Otaki/issues/175`).

## Full Workflow

```bash
ISSUE_URL=$(gh issue create \
  --repo Svagtlys/Otaki \
  --title "bug(scheduler): overdue polls silently dropped" \
  --label "bug" \
  --milestone "1.3 — Quality" \
  --body "$(cat issue-body.md)")

gh project item-add 6 --owner Svagtlys --url "$ISSUE_URL"
```

## Common Mistakes

- **Narrative titles** — "I noticed that when I click the button nothing happens" → `bug(ui): button click does nothing`
- **No area** — `bug: something broken` → `bug(scheduler): overdue polls silently dropped`
- **Over-detailed body** — Include only recreation info, not implementation plans or conversation history
- **No milestone** — Every issue must have a milestone
- **Wrong label** — `bug` = broken behavior, `enhancement` = new capability

## Red Flags

- Title exceeds 70 characters
- Body includes "I think we should..." or "maybe we could..."
- No reproduction steps for bugs
- No milestone assigned