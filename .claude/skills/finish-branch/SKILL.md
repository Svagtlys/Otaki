---
description: Finish a feature branch for Otaki — verifies tests pass, checks docs are up to date, confirms commits with the user, then pushes and marks the PR ready for review. Use when implementation is complete.
allowed-tools: Bash, Read, Glob, Grep
---

Finish a feature branch: verify tests and docs, confirm commits with the user, then push and mark the PR ready.

## Steps

### 1. Identify the PR and touched areas

- Run `git diff develop...HEAD --name-only` to get all files changed on this branch
- Run `gh pr list --head $(git branch --show-current) --json number,title,url` to find the open draft PR
- If no PR is found, tell the user and stop

### 2. Confirm tests pass

- Identify which test areas are relevant based on the changed files (e.g. if `api/comics.py` changed, run comic API tests; if `services/source_selector.py` changed, run source selector tests)
- Run the relevant existing tests and any new tests added on this branch
- If any tests fail: **stop, report the failures, and do not proceed** until the user addresses them

### 3. Confirm docs are up to date

Check each of the following docs against the code changes on this branch. For each one, flag any gaps:

- `docs/API.md` — does it reflect every new or changed endpoint?
- `docs/ARCHITECTURE.md` — does it reflect every new or changed service/worker/method?
- `docs/FLOWS.md` — do any flows need updating?
- `CONTRIBUTING.md` — any process changes?

If any doc is missing coverage for a code change, **do not proceed** — tell the user exactly what needs updating.

### 4. Confirm commits with the user

Show the user a summary of what will be committed:
- Run `git status` and `git diff --stat`
- List all unstaged/staged changes grouped by file
- Propose commit(s) using the format `type(scope): description` per `CONTRIBUTING.md`
  - If there are logical groupings (e.g. API changes separate from service changes, docs separate from code), propose multiple commits
  - Always put doc updates in a separate commit from code changes

**Wait for explicit user approval of the commit plan before making any commits.**

### 5. Make commits and push

After the user approves:
- Stage and commit exactly as agreed
- Push to the remote branch: `git push`
- Confirm the push succeeded

### 6. Mark PR as ready for review

```bash
gh pr ready
```

Show the user the PR URL and confirm it is now marked ready.
