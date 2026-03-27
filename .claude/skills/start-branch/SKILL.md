---
description: Start a new feature branch for Otaki issues — checks blockers, creates branch off develop, opens a draft PR, then plans the implementation. Use when beginning work on one or more GitHub issues.
argument-hint: <issue-number(s)>
allowed-tools: Bash, Read, Glob, Grep
---

Start a new feature branch for one or more GitHub issues.

Arguments: $ARGUMENTS

## Steps

### 1. Confirm issues are unblocked and ready

For each issue number provided in $ARGUMENTS:
- Fetch the issue from GitHub using `gh issue view <number>`
- Check the issue's body and comments for any blockers (phrases like "blocked by", "depends on", "waiting on")
- Confirm the issue is assigned to the **Otaki** milestone
- Confirm the issue's project status is **Ready** (not In Progress, In Review, or Backlog)

If any issue is blocked, not on the Otaki milestone, or not in Ready status: **stop and tell the user** — do not proceed until they confirm.

### 2. Determine branch name

- Read the issue title(s) and number(s)
- Propose a branch name using the format: `feat/<short-description>` or `fix/<short-description>` based on the issue type
- Use lowercase kebab-case, keep it under 40 chars
- Tell the user the proposed branch name and ask them to confirm or change it before creating

### 3. Create the branch off develop

```bash
git fetch origin
git checkout -b <branch-name> origin/develop
```

### 4. Create an empty commit and open a draft PR

Create an empty commit to start the branch:
```bash
git commit --allow-empty -m "chore: start branch for #<issue-number(s)>"
git push -u origin <branch-name>
```

Then open a draft PR against `develop` that links to all issues:
- Title: match the primary issue title
- Body: closes each issue with `Closes #<number>` (one per line)
- Use `gh pr create --draft --base develop`

Show the user the PR URL when done.

### 5. Enter planning mode

After the PR is created, switch to plan mode to design the implementation.

Before planning, read the relevant design docs:
- `PLAN.md`
- `docs/ARCHITECTURE.md`
- `docs/API.md`
- `docs/FLOWS.md`

Then produce a concrete implementation plan covering:
- Files to create or modify
- New endpoints, services, or worker logic
- Database model changes (if any)
- Tests required (integration tests for all new endpoints/services)
- Doc updates needed (`docs/API.md`, `docs/ARCHITECTURE.md`, etc.)

Present the plan and wait for the user to approve before any code is written.
