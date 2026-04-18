---
description: Release Otaki — cuts a release/x.y branch from develop, merges to main (no squash), tags, pushes (fires GHCR publish workflow), and syncs back to develop. Use when all features for a release are merged into develop and you're ready to ship.
modeSlugs:
  - architect
---

Cut and publish an Otaki release following the branching strategy in `docs/CONTRIBUTING.md`.

Version to release: $ARGUMENTS

## Steps

### 1. Resolve the version

If $ARGUMENTS is empty, ask the user: "What version are you releasing? (e.g. 1.0.0)"

Strip any leading `v` from the input — work with bare semver (e.g. `1.0.0`). The git tag will be `v1.0.0`.

Determine the minor series (e.g. `1.0.0` → series `1.0`, `1.2.3` → series `1.2`). The release branch will be `release/1.0`.

### 2. Verify develop is ready

```bash
git fetch origin
git checkout develop
git status
git log origin/develop..HEAD --oneline
```

- Confirm the working tree is clean (no uncommitted changes)
- Confirm the local develop is up to date with `origin/develop`
- If either check fails, **stop and tell the user** — do not proceed

List any open PRs targeting develop, so the user can confirm they're not waiting on anything:

```bash
gh pr list --base develop --state open
```

If there are open PRs, show them and ask the user: "These PRs are still open against develop. Proceed anyway?" — **wait for a yes before continuing.**

### 3. Check the milestone for unfinished issues

Look up the GitHub milestone matching the release version and list any issues that are not yet closed:

```bash
gh issue list --milestone "<version>" --state open
```

If `<version>` doesn't match a milestone name, try the minor series (e.g. `1.0` for version `1.0.0`) or list milestones to find the right one:

```bash
gh api repos/Svagtlys/Otaki/milestones --jq '.[] | {title, open_issues, closed_issues}'
```

If there are any open issues in the milestone, show them to the user and ask: "These issues are still open on the milestone. Are they deferred to a later release, or do they need to be completed first?" — **wait for a yes before continuing.**

### 4. Check the ROADMAP for the release

Read `docs/ROADMAP.md` and find the checklist for the version being released. Show the user which items are still marked `[ ]` (unchecked) and ask: "These roadmap items appear unchecked. Are they all actually complete, or are any genuinely unfinished?" — **wait for confirmation before continuing.**

### 4. Confirm the plan with the user

Show the user exactly what will happen:

```
Release plan for v<version>:

  1. git checkout -b release/<series> origin/develop
  2. git checkout main && git merge --no-ff --no-squash release/<series>
  3. git tag v<version>
  4. git push origin main
  5. git push origin v<version>          ← fires the GHCR publish workflow
  6. git checkout develop && git merge --no-ff --no-squash release/<series>
  7. git push origin develop

After step 5, the GitHub Actions workflow will build and push:
  ghcr.io/svagtlys/otaki-backend:v<version>
  ghcr.io/svagtlys/otaki-frontend:v<version>

⚠  If this is the first release: after the workflow completes, manually set
   both packages to public in GitHub → Packages settings.
```

**Wait for explicit user approval before running any git commands.**

### 5. Cut the release branch

```bash
git checkout -b release/<series> origin/develop
git push -u origin release/<series>
```

### 6. Merge into main (no squash)

```bash
git checkout main
git pull origin main
git merge --no-ff release/<series> -m "chore(release): merge release/<series> into main"
```

If there are merge conflicts, **stop and tell the user** — do not attempt to resolve them automatically.

### 7. Tag and push

```bash
git tag v<version>
git push origin main
git push origin v<version>
```

Confirm the tag was pushed:

```bash
gh run list --workflow publish.yml --limit 3
```

Show the user the Actions run URL and tell them the workflow is running.

### 8. Sync release branch back to develop (no squash)

```bash
git checkout develop
git merge --no-ff release/<series> -m "chore(release): merge release/<series> back into develop"
git push origin develop
```

### 9. Finish

Report to the user:

```
✓ release/<series> cut from develop
✓ main updated and tagged v<version>
✓ GHCR publish workflow triggered
✓ develop synced from release/<series>

Next steps:
- Watch the workflow at: https://github.com/Svagtlys/Otaki/actions
- If this is the first release: set otaki-backend and otaki-frontend packages
  to public at https://github.com/Svagtlys?tab=packages
- Update the image tags in deploy/docker-compose.yml if they haven't been
  updated yet (they should already match v<version>)
```
