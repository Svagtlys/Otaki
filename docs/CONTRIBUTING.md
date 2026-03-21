# Contributing to Otaki

---

## Commit Conventions

Otaki uses [Conventional Commits](https://www.conventionalcommits.org/).

```
<type>(<scope>): <short description>
```

### Types

| Type | Use for |
|---|---|
| `feat` | New feature or behaviour |
| `fix` | Bug fix |
| `docs` | Documentation only (md files, docstrings, comments) |
| `refactor` | Code change with no behaviour change |
| `test` | Adding or fixing tests |
| `chore` | Tooling, deps, config, CI — no production code |
| `style` | Formatting only (whitespace, linting) |

### Scopes

Use the module or area being changed. Common scopes:

`auth`, `scheduler`, `source-router`, `quality`, `downloader`, `relocator`, `api`, `ui`, `db`, `setup`

### Examples

```
feat(scheduler): add per-comic upgrade job registration
fix(source-router): apply comic-local overrides before global priority sort
docs(flows): add first-time setup flow diagram
chore(deps): pin opencv to 4.9.0
refactor(cadence-inferrer): extract hiatus filter into helper function
```

### Rules

- **Subject line ≤ 72 characters.** Wrap body at 80.
- **Imperative mood** in the subject: "add", "fix", "remove" — not "added", "fixes".
- **No period** at the end of the subject line.
- Use the body to explain *why*, not *what*. The diff already shows what changed.
- Reference issues or decisions in the footer if relevant: `Closes #12`, `Ref: docs/PLAN.md § C`.

---

## Commit Size

**One logical change per commit.** A good commit can be reviewed and reverted independently without breaking anything else.

### Too big
- "Implement source router, quality scanner, and file relocator" — that's three commits.
- Mixing a bug fix with a refactor in the same commit.

### Too small
- Committing a half-implemented function that can't run.
- Splitting a rename across multiple commits with no clear boundary.

### Right size
- A new service with its corresponding model changes and a router endpoint that calls it.
- A bug fix with the failing test that proves it.
- A config field addition with the code that reads it.

When in doubt: **if the commit message needs "and" to describe what changed, split it.**

---

## Versioning

Otaki uses [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.

| Increment | When |
|---|---|
| `PATCH` (1.0.**1**) | Bug fix, no new behaviour |
| `MINOR` (1.**1**.0) | New feature, backward compatible |
| `MAJOR` (**2**.0.0) | Breaking change (API, schema migration, config rename) |

---

## Branching

### Permanent branches

| Branch | Purpose |
|---|---|
| `main` | Always reflects the latest tagged release. Never commit directly. |
| `develop` | Integration branch for the next minor or major release. All feature branches merge here. |

### Temporary branches

| Pattern | Branch from | Merges into | Purpose |
|---|---|---|---|
| `feature/<name>` | `develop` | `develop` | New functionality for the next release |
| `fix/<name>` | `release/x.y` | `release/x.y` + `develop` | Bug fix against a released version |
| `hotfix/<name>` | `main` | `main` + `develop` | Critical production fix that can't wait for a release cycle |
| `release/x.y` | `develop` | `main` | Stabilisation branch for a minor release; only bug fixes allowed once cut |
| `docs/<name>` | `develop` | `develop` | Documentation-only changes |
| `chore/<name>` | `develop` | `develop` | Tooling, deps, CI — no production code |

### Targeting different versions simultaneously

The common case: feature X is destined for 1.2 but there are bug fixes needed on the live 1.1 release.

```
main ──── tag:1.1.0 ──────────────────── tag:1.1.1 ──── tag:1.2.0 ──▶
               │                              │
               └── release/1.1 ── fix/foo ───┘ (merged to main, cherry-picked to develop)

develop ───────────────────────── feature/bar ─────────────────────────▶
```

1. Cut `release/1.1` from `main` at the `1.1.0` tag
2. `fix/foo` branches from `release/1.1`, merges back into `release/1.1`
3. Tag `release/1.1` as `1.1.1` and merge into `main`
4. Cherry-pick the fix commit(s) into `develop` so the fix is not lost in the next release
5. `feature/bar` runs independently on `develop` — it never touches `release/1.1`

**Rule:** nothing targeting a future minor version ever touches a `release/x.y` branch.

---

## Squashing

| Merge | Squash? | Reason |
|---|---|---|
| `feature/*` → `develop` | **Yes** | One commit per feature keeps `develop` history readable |
| `fix/*` → `release/x.y` | **Yes** | One commit per fix; easier to cherry-pick to `develop` |
| `hotfix/*` → `main` | **Yes** | Same as fix |
| `release/x.y` → `main` | **No** | Preserve the individual fix commits in `main` history |
| `release/x.y` → `develop` (post-release sync) | **No** | Preserve for traceability |

Squash at merge time using `git merge --squash` or the "Squash and merge" button. Write a clean commit message for the squashed commit using the [Conventional Commits](#commit-conventions) format — do not use the auto-generated list of individual commits.

### WIP commits during development

While a branch is in progress, commit freely and messily — short WIP commits, fixups, etc. Before merging, either:
- **Squash at merge time** (preferred — no rebase needed), or
- **Interactive rebase** to clean up the branch history before the merge if the individual commits are worth preserving in the squash message body

**If a branch has been pushed to GitHub and `develop` has moved on**, do not rebase — merge `develop` into the feature branch instead:

```bash
git fetch origin
git merge origin/develop
# resolve any conflicts, then commit
```

This creates a merge commit on the feature branch, which is fine — it gets squashed away when the branch merges into `develop`, so `develop`'s history stays clean regardless.

**Exception — solo branch:** if you are certain no one else has the branch checked out locally, you can rebase and force-push:

```bash
git rebase origin/develop
git push --force-with-lease
```

`--force-with-lease` is safer than `--force`: it refuses to push if the remote has commits you haven't seen, catching the case where someone else pushed to the branch between your fetch and push.

---

## LLM Assistance

Otaki welcomes the use of LLM coding assistants (Claude, Copilot, etc.). The following guidelines ensure AI-assisted code meets the same standard as hand-written code.

### What to use LLMs for

- Generating boilerplate (models, routers, Alembic migrations)
- Drafting logic you then review and refine
- Explaining unfamiliar APIs or libraries
- Writing test cases for behaviour you have already specified
- Updating documentation to match code changes

### What to be careful about

- **Never commit AI output without reading it.** LLMs hallucinate — they will invent method names, API fields, and library behaviours that don't exist. Verify any Suwayomi GraphQL field names, Python library calls, or filesystem behaviours against primary sources before committing.
- **Don't let an LLM choose architecture.** Use the docs in `/docs` as architecture guidance. If an LLM suggests a different design, evaluate it explicitly rather than letting it drift in unreviewed.
- **Watch for scope creep.** LLMs tend to add extra error handling, abstractions, and "improvements" that weren't requested. Accept only what was asked for.
- **Test before committing.** AI-generated logic that looks correct can have subtle edge-case bugs. Run it against real inputs.

### Commit attribution

If a commit contains substantial AI-generated content, add a trailer to the commit body:

```
Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

This is a courtesy signal, not a requirement for small suggestions or completions.

### Reviewing AI-generated PRs

When reviewing a PR that used LLM assistance, pay extra attention to:

- Any new dependency or third-party API call (verify it exists and the usage is correct)
- Edge cases the LLM likely didn't consider (empty results, missing files, auth failures)
- Whether the change matches the plan in `/docs` — LLMs will confidently deviate

---

## Documentation

If your change affects behaviour described in `docs/`, update the docs in the same commit. The files to keep in sync:

| File | Update when |
|---|---|
| `PLAN.md` | Data model, workflow, or config changes |
| `docs/ARCHITECTURE.md` | File responsibilities, method signatures, worker logic |
| `docs/API.md` | Any API input/output schema change |
| `docs/FLOWS.md` | User-facing or system flow changes |
| `TODO.md` | New known issues or completed items |

---

## Testing

- Write tests for any non-trivial logic before or alongside the implementation.
- Tests live in `backend/tests/`, mirroring the app structure.
- Integration tests that touch Suwayomi must use a real running instance — no mocking the Suwayomi client itself.
- Quality scanner tests must include real CBZ fixtures, not mocked image data.
