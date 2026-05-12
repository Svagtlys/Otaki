# Search Page Design

**Date:** 2026-03-26
**Issue:** #22
**Branch:** feat/search-page

---

## Overview

A two-step search page at `/search`. Users search for a manga title, select one or more result cards (representing the same series from different sources), then fill in a request form and submit. Consistent with the plain inline-style approach used in `Library.tsx`.

---

## Navigation

- Library page (`Library.tsx`): "Search" link added top-right of the heading area.
- Search page (`Search.tsx`): "← Library" link in the same position.
- Both use `useNavigate`/`Link` — no shared nav component.

---

## Step 1: Search & Select

### Search input
- Text input at the top of the page.
- Debounced 400ms before firing the query.
- TanStack Query: `queryKey: ['search', q]`, disabled when `q` is empty.
- Endpoint: `GET /api/search?q=<query>`

### Result cards
- Rendered as a grid.
- Each card shows: cover image (48×64, `objectFit: cover`), title, source label, synopsis snippet (~2 lines, truncated with CSS).
- Clicking a card toggles its selected state. Selected cards get a highlighted border (inline style).

### Basket & advance
- "Review request (N)" button appears once ≥1 card is selected.
- Clicking it advances to Step 2.

### States
- Loading: `<p>Loading…</p>`
- Empty (query entered, no results): `<p>No results.</p>`
- Error: `<p style={{ color: 'red' }}>{errorDetail}</p>`
- Idle (no query): nothing shown below the input.

---

## Step 2: Request Form

Replaces the results area. Displayed below the search bar (which becomes read-only / hidden).

### Selected cards summary
- One line per selected card: title + source label.
- "← Back to results" link restores Step 1 with selections intact.

### Fields

| Field | Pre-fill | Behaviour |
|---|---|---|
| Display name | First selected card's title | Free text |
| Library title | Same as display name | Syncs with display name via `onChange` until user manually edits it (`libraryTitleTouched` flag) |

### Cover picker
- Shows each selected card's cover as a small image (48×64).
- Clicking one sets it as the chosen cover (highlighted border).
- Defaults to the first selected card's cover.

### Submit
- Calls `POST /api/requests` with `{ primary_title, library_title, cover_url }`.
- On success: navigate to `/library`.
- On error: show error text inline below the button.

---

## Files

### Creates
- `frontend/src/pages/Search.tsx`

### Modifies
- `frontend/src/App.tsx` — replace `<Placeholder name="Search" />` with `<Search />`
- `frontend/src/pages/Library.tsx` — add "Search" link next to the `<h1>`

---

## State

All state is local React (`useState`). No global store needed.

| State | Type | Description |
|---|---|---|
| `query` | `string` | Current search input value |
| `debouncedQuery` | `string` | Debounced value passed to TanStack Query |
| `selected` | `Set<string>` (url) | URLs of selected result cards (unique per source result) |
| `step` | `1 \| 2` | Current step |
| `displayName` | `string` | Request display name field value |
| `libraryTitle` | `string` | Library title field value |
| `libraryTitleTouched` | `boolean` | Whether user has manually edited library title |
| `chosenCoverUrl` | `string \| null` | Selected cover URL |

---

## API

| Method | Endpoint | Used for |
|---|---|---|
| `GET` | `/api/search?q=` | Fetch results in Step 1 |
| `POST` | `/api/requests` | Submit request in Step 2 |

---

## Tests

- `frontend/e2e/search.spec.ts` — Playwright tests covering:
  - Search input triggers results
  - Card selection toggles highlight and updates basket count
  - Advancing to Step 2 shows form with correct pre-fills
  - Library title syncs with display name until manually edited
  - Cover picker defaults to first card; clicking another updates selection
  - Submit navigates to `/library` on success
  - Error state shown on failed submit
  - "← Back to results" preserves selections
  - "← Library" nav link works from Search; "Search" link works from Library
