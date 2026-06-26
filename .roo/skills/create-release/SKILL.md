---
name: create-release
description: Use when creating a new Otaki release — minor/major version bumps, tagging, merging develop to main, cutting release branches, or triggering Docker image publishes to GHCR. Triggers when the user says "release", "ship", "tag a version", "bump version", or "publish Docker images".
---

# Create Release

## Overview

Create a new Otaki release by merging `develop` into `main`, tagging the version, and triggering the automated Docker publish workflow.

**Core principle:** Releases are created by tagging `main`. Everything else (tests, migrations, builds) must pass before tagging.

## When to Use

- User says "release version X.Y.Z", "ship v1.2.0", "tag a new release"
- User says "bump to version X.Y", "publish Docker images"
- Feature work on `develop` is complete and ready for release
- Preparing a minor or major release (not hotfixes — use `merge-hotfix` skill)

**Do NOT use when:** Fixing a critical production bug (use hotfix flow instead).

## Versioning Rules

Otaki uses [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.

| Increment | When | Example |
|---|---|---|
| `PATCH` (1.0.**1**) | Bug fix, no new behavior | `1.0.1` |
| `MINOR` (1.**1**.0) | New feature, backward compatible | `1.1.0` |
| `MAJOR` (**2**.0.0) | Breaking change (API, schema, config) | `2.0.0` |

## Branch Model

| Branch | Purpose |
|---|---|
| `main` | Latest tagged release. **Never commit directly.** |
| `develop` | Integration branch for next release. All features merge here. |
| `release/x.y` | Archival branch per shipped minor version. Cut from `main` at first `x.y.0` tag. |

## Pre-Release Checklist

**Run these commands on `develop` BEFORE creating the release PR:**

```bash
# 1. Ensure develop is up to date
git checkout develop
git fetch origin
git merge origin/develop

# 2. Run all tests (MUST pass, including INTEGRATION)
backend/.venv/bin/pytest

# 3. Lint check (MUST be clean)
backend/.venv/bin/ruff check .

# 4. DB migrations current (MUST be applied)
cd backend && backend/.venv/bin/alembic upgrade head

# 5. Frontend builds (MUST succeed)
cd frontend && npm run build

# 6. Verify no uncommitted changes
git status
```

### If Any Step Fails

Create a fix branch from `develop`, resolve the issue, and open a PR into `develop` titled `chore: prep for release v<X.Y.Z>`. Follow the [`create-work-item`](.roo/skills/create-work-item/SKILL.md:1) skill to track the work item if the fix is non-trivial.

```bash
git checkout -b chore/prep-release-v<X.Y.Z>
# fix the issue(s)
git commit -m "chore: fix <issue> for v<X.Y.Z> release"
git push origin chore/prep-release-v<X.Y.Z>
gh pr create --base develop --title "chore: prep for release v<X.Y.Z>"
```

Wait for the PR to be reviewed and merged into `develop` before proceeding.

## Release Flow (Minor/Major)

### Step 1: Create Release PR (`develop` → `main`)

Once the pre-release checklist passes on `develop`, open a PR to merge into `main`:

```bash
gh pr create --base main --head develop --title "release: v<X.Y.Z>" --body "Release v<X.Y.Z>

- [x] All tests passing (including integration)
- [x] Lint clean
- [x] DB migrations current
- [x] Frontend builds successfully
"
```

**Merge settings:** Use **"Create a merge commit"** (not squash, not rebase). This is equivalent to `--no-ff` and preserves the merge commit for traceability.

Wait for CI to pass, then merge the PR.

### Step 2: Tag the Release

After the PR is merged, tag `main`:

```bash
git checkout main
git fetch origin
git tag -a v<X.Y.Z> -m "Release v<X.Y.Z>"
git push origin v<X.Y.Z>
```

**Tag format:** `v` prefix followed by semver (e.g., `v1.1.0`, `v2.0.0`).

Pushing the tag triggers the [publish workflow](.github/workflows/publish.yml:1) automatically.

### Step 3: Verify Docker Publish

The tag push triggers `.github/workflows/publish.yml` which:

1. Builds **backend** multi-arch (`linux/amd64`, `linux/arm64`)
2. Builds **frontend** (`linux/amd64`)
3. Tags both with version (e.g., `1.1.0`) and `latest`
4. Pushes to GHCR (`ghcr.io/svagtlys/otaki-backend`, `ghcr.io/svagtlys/otaki-frontend`)

Monitor the workflow run:

```bash
gh run list --workflow=publish.yml --limit 1
gh run view --log
```

### Step 4: Cut `release/x.y` Branch (First Release of Minor)

For the **first** release of a minor version (e.g., `1.1.0`), cut the archival branch:

```bash
git branch release/<X.Y> v<X.Y.Z>
git push origin release/<X.Y>
```

This branch is append-only with hotfixes. Future hotfixes for this minor version will branch from `main` and merge into `release/x.y`.

## Hotfix Flow

**Do NOT use this skill for hotfixes.** Use the `merge-hotfix` skill instead.

Hotfixes branch off `main` and land in three places:

```
hotfix/<name>  →  main            (tag v<major>.<minor>.<patch>, fires GHCR publish)
               →  release/<x.y>   (keeps archival branch current)
               →  develop         (backport so in-progress work picks up the fix)
```

## Common Mistakes

| Mistake | Fix |
|---|---|
| Committing directly to `main` | Merge from `develop` or `hotfix/*` only |
| Forgetting `--no-ff` on merge | Always use `--no-ff` to preserve merge history |
| Tagging before tests pass | Run full checklist before tagging |
| Missing `v` prefix in tag | Tag must be `v1.2.3`, not `1.2.3` |
| Cutting `release/x.y` from `develop` | Cut from `main` at the tag point |
| Merging future features into `release/x.y` | `release/x.y` is append-only with hotfixes only |

## Quick Reference

| Action | Command |
|---|---|
| Run tests | `backend/.venv/bin/pytest` |
| Lint check | `backend/.venv/bin/ruff check .` |
| DB migrate | `cd backend && backend/.venv/bin/alembic upgrade head` |
| Frontend build | `cd frontend && npm run build` |
| Merge develop→main | `git merge origin/develop --no-ff -m "chore: merge develop into main for v<X.Y.Z>"` |
| Tag release | `git tag -a v<X.Y.Z> -m "Release v<X.Y.Z>"` |
| Push tag | `git push origin v<X.Y.Z>` |
| Cut release branch | `git push origin release/<X.Y>` |
| Check publish workflow | `gh run list --workflow=publish.yml` |

## Squash Rules

| Merge | Squash? |
|---|---|
| `feature/*` → `develop` | **Yes** |
| `fix/*` → `release/x.y` | **Yes** |
| `develop` → `main` | **No** (`--no-ff`) |
| `hotfix/*` → anywhere | **No** (`--no-ff`) |
| `release/x.y` → `main` | **No** |

## Real-World Impact

Following this process ensures:
- `main` always reflects a working, tagged release
- Docker images are published automatically with correct version tags
- Users can pin to specific versions or use `latest`
- Archival `release/x.y` branches provide exact code for each minor version
- Hotfixes can be applied to both live and development branches simultaneously