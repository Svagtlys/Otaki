---
description: Merge one or more hotfix branches into main, tag a patch release, push (fires GHCR publish), and backport to develop. Use when hotfix PRs are approved and ready to ship as a patch release.
argument-hint: <version> (e.g. 1.0.1)
modeSlugs:
  - architect
---

Merge approved hotfix PRs, tag a patch release, and backport fixes to develop.

Patch version: $ARGUMENTS

## Steps

### 1. Resolve the version

If $ARGUMENTS is empty, ask the user: "What patch version are you releasing? (e.g. 1.0.1)"

Strip any leading `v` — work with bare semver. The git tag will be `v<version>`.

### 2. List hotfix PRs ready to merge

```bash
gh pr list --base main --state open --json number,title,headRefName,reviewDecision,url
```

Show the list to the user. For each PR, note whether it is approved or still pending review.

If any PRs are not yet approved, ask: "These PRs are not yet approved: [list]. Merge the approved ones now, or wait for all?" — **wait for the user's answer before continuing.**

### 3. Verify main is clean and up to date

```bash
git fetch origin
git checkout main
git status
git log origin/main..HEAD --oneline
```

- Confirm the working tree is clean
- Confirm local main matches `origin/main`

If either check fails, **stop and tell the user** — do not proceed.

### 4. Determine the active release branch

Check whether a `release/<major>.<minor>` branch exists for the version being patched:

```bash
git branch -r | grep "release/$(echo <version> | cut -d. -f1-2)"
```

- If it exists (e.g. `release/1.0`), hotfixes go to **both** `main` and `release/<major>.<minor>`.
- If it does not exist, hotfixes go to `main` only (release branch will be cut when the minor version ships).

### 5. Confirm the plan with the user

Show the user exactly what will happen:

```
Hotfix release plan for v<version>:

  PRs to merge into main (no squash):
    - #<N> <title> (hotfix/<branch>)
    ...

  Also merge into release/<major>.<minor>:   ← only if branch exists
    - same PRs (keeps release branch current for archival)

  Then:
    git tag v<version>
    git push origin main
    git push origin release/<major>.<minor>  ← only if branch exists
    git push origin v<version>               ← fires the GHCR publish workflow

  Backport each hotfix branch to develop:
    git checkout develop
    git merge --no-ff hotfix/<branch>   (repeated for each PR)
    git push origin develop
```

**Wait for explicit user approval before running any git commands.**

### 6. Merge each hotfix PR into main

For each approved PR, merge it (no squash) directly via the branch:

```bash
git checkout main
git merge --no-ff hotfix/<branch> -m "chore(hotfix): merge hotfix/<branch> into main"
```

If a merge has conflicts, **stop and tell the user** — do not attempt to resolve them automatically.

After all merges:

```bash
git log --oneline -5
```

Show the user the resulting main commit history.

### 7. Merge each hotfix PR into release/<major>.<minor> (if branch exists)

```bash
git checkout release/<major>.<minor>
git pull origin release/<major>.<minor>
```

For each hotfix branch:

```bash
git merge --no-ff hotfix/<branch> -m "chore(hotfix): merge hotfix/<branch> into release/<major>.<minor>"
```

If a merge has conflicts, **stop and tell the user** — do not proceed.

### 8. Tag and push

```bash
git tag v<version>
git push origin main
git push origin release/<major>.<minor>  # only if branch exists
git push origin v<version>
```

Confirm the publish workflow fired:

```bash
gh run list --workflow publish.yml --limit 3
```

Show the user the Actions run URL.

### 9. Backport each hotfix branch to develop

```bash
git checkout develop
git pull origin develop
```

For each hotfix branch:

```bash
git merge --no-ff hotfix/<branch> -m "chore(hotfix): backport hotfix/<branch> to develop"
```

If a backport has conflicts, **stop and tell the user** — do not proceed with remaining backports until this is resolved.

After all backports:

```bash
git push origin develop
```

### 10. Finish

Report to the user:

```
✓ Hotfix PRs merged into main
✓ Hotfix PRs merged into release/<major>.<minor>   ← only if branch existed
✓ main tagged v<version>
✓ GHCR publish workflow triggered
✓ Hotfixes backported to develop

Next steps:
- Watch the workflow at: https://github.com/Svagtlys/Otaki/actions
- Update deploy/docker-compose.yml image tags to v<version> if not already done
- Close any related GitHub issues if not auto-closed by the merged PRs
```
