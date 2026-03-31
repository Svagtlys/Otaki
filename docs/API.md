# API Reference

All endpoints are served under `/api`. Requests and responses use JSON unless otherwise noted. The backend is async (FastAPI); all endpoints support concurrent requests.

**Authentication:** All endpoints except `/api/setup/*` and `/api/auth/*` require a valid session token. Pass it as:
- `Authorization: Bearer <token>` header, or
- `otaki_session` cookie

Obtain a token via `POST /api/auth/login`. Requests without a valid token return `401 Unauthorized`.

---

## Table of Contents

- [Setup](#setup)
- [Auth](#auth)
- [Search](#search)
- [Requests (Comics)](#requests-comics)
- [Settings](#settings)
- [Sources](#sources)
- [Watermark Templates](#watermark-templates)
- [Quality](#quality)
- [Common Types](#common-types)
- [Error Responses](#error-responses)
- [Limitations](#limitations)

---

## Setup

The setup wizard walks through first-time configuration. Steps 2–5 are guarded: once `SETUP_COMPLETE=True` is written to `.env` (at the end of step 5), they return `409`. The status and completion-check endpoints have no guard and are always callable.

Exempt from the auth middleware — no token required, except `GET /api/setup/status` which requires auth.

### `GET /api/setup/complete`

Lightweight public check used by the frontend on load to decide whether to show the setup wizard or the normal app.

**Response `200`**

```json
{ "complete": false }
```

---

### `GET /api/setup/status`

Full setup state, used by the wizard to prefill fields on re-entry. Requires auth — call after step 1 completes and a token is available.

**Headers**

| Header | Required | Description |
|---|---|---|
| `Authorization` | yes | `Bearer <token>` |

**Response `200`**

```json
{
  "complete": false,
  "admin_created": true,
  "suwayomi_url": "http://suwayomi:4567",
  "suwayomi_username": "admin",
  "download_path": null,
  "library_path": null
}
```

**Error Cases**
- `401 Unauthorized` — missing or invalid token.

---

### `POST /api/setup/user`

Create the first admin user (step 1). Not guarded by `SETUP_COMPLETE`.

**Request Body**

```json
{ "username": "admin", "password": "mypassword" }
```

**Response `200`** — no body.

**Error Cases**
- `409 Conflict` — an admin user already exists.

---

### `POST /api/setup/connect`

Connect to Suwayomi (step 2). Validates connectivity and writes credentials to `.env`.

**Request Body**

```json
{ "url": "https://suwayomi.example.com", "username": "user", "password": "pass" }
```

**Response `200`** — no body.

**Error Cases**
- `400 Bad Request` — could not reach Suwayomi with the supplied credentials.
- `409 Conflict` — setup already complete (`SETUP_COMPLETE=True`).

---

### `GET /api/setup/sources`

List sources installed in Suwayomi for priority ordering (step 3).

**Response `200`**

```json
[
  { "id": "1998944621602222888", "name": "MangaDex", "lang": "en", "icon_url": "https://..." }
]
```

**Error Cases**
- `409 Conflict` — setup already complete.

---

### `POST /api/setup/sources`

Save source priority order (step 3). First item = highest priority.

**Request Body**

```json
{
  "sources": [
    { "id": "1998944621602222888", "name": "MangaDex", "lang": "en", "icon_url": "https://..." }
  ]
}
```

**Response `200`** — no body. Idempotent — replaces all existing `Source` rows.

**Error Cases**
- `409 Conflict` — setup already complete.

---

### `POST /api/setup/paths`

Set filesystem paths (step 4). On success, writes `SETUP_COMPLETE=True` to `.env`, locking all guarded setup endpoints.

**Request Body**

```json
{
  "download_path": "/data/suwayomi/downloads",
  "library_path": "/data/library",
  "create": false
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `download_path` | string | — | Suwayomi's download staging directory |
| `library_path` | string | — | Final library directory |
| `create` | bool | `false` | If `true`, create missing directories with `mkdir -p` |

**Response `200`** — no body.

**Error Cases**
- `400 Bad Request` (directories missing) — one or more paths do not exist and `create=false`. Response body identifies which paths are missing:
  ```json
  {
    "detail": {
      "code": "directories_missing",
      "missing": [
        { "field": "download_path", "path": "/data/suwayomi/downloads" }
      ]
    }
  }
  ```
  The frontend shows a confirmation screen; resubmit with `create=true` to create them.
- `400 Bad Request` (permission denied) — `create=true` but the directory could not be created.
- `409 Conflict` — setup already complete.

---

## Auth

### `POST /api/auth/login`

Exchange credentials for a JWT session token.

**Request Body**

```json
{ "username": "admin", "password": "mypassword" }
```

**Response `200`**

```json
{ "access_token": "eyJ...", "token_type": "bearer" }
```

Include the token on subsequent requests:
```
Authorization: Bearer eyJ...
```

**Error Cases**
- `401 Unauthorized` — username not found or password incorrect (response does not distinguish between the two).

---

### `POST /api/auth/logout`

**Response `200`** — no body. Stateless: the token is not invalidated server-side; the client should discard it.

---

### `GET /api/auth/me`

Return the current user's profile.

**Headers**

| Header | Required | Description |
|---|---|---|
| `Authorization` | yes | `Bearer <token>` |

**Response `200`**

```json
{ "id": 1, "username": "admin" }
```

**Error Cases**
- `401 Unauthorized` — missing, malformed, or expired token.

---

## Search

### `GET /api/search`

Search for a manga title across all enabled sources. Results are **not deduplicated** — the same series may appear multiple times with different titles across sources. The user selects which results belong to the same series when submitting a request.

**Query Parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `q` | string | yes | Title search query |

**Response `200`**

```json
{
  "results": [
    {
      "title": "One Piece",
      "cover_url": "https://...",
      "cover_display_url": "/api/search/thumbnail?url=...",
      "synopsis": "...",
      "source_id": 1,
      "source_name": "MangaDex",
      "url": "https://source-url/manga/one-piece"
    },
    {
      "title": "ワンピース",
      "cover_url": "https://...",
      "cover_display_url": "/api/search/thumbnail?url=...",
      "synopsis": "...",
      "source_id": 2,
      "source_name": "MangaPlus",
      "url": "https://source2-url/manga/wan-piisu"
    }
  ],
  "source_errors": [
    { "source_name": "BrokenSource", "reason": "connection timed out" }
  ]
}
```

`results` fields:

| Field | Type | Notes |
|---|---|---|
| `title` | string | Title as returned by this source |
| `cover_url` | string \| null | Absolute Suwayomi cover URL — submitted to `POST /api/requests` |
| `cover_display_url` | string \| null | Proxied `/api/search/thumbnail?url=…` — used by `<img>` tags |
| `synopsis` | string \| null | Short description, may be empty |
| `source_id` | int | Otaki source ID |
| `source_name` | string | Human-readable source label |
| `url` | string | Source-specific manga URL, passed back when submitting a request |

`source_errors` fields:

| Field | Type | Notes |
|---|---|---|
| `source_name` | string | Name of the source that failed |
| `reason` | string | Human-readable failure reason: `"connection timed out"`, `"connection refused or DNS failure"`, `"authentication failed (401)"`, `"unexpected HTTP <N>"`, or `"unexpected error"` |

**Notes**
- Fans out to all enabled sources in parallel; slow sources are waited on up to a timeout.
- No deduplication — the frontend shows all results and lets the user select which ones represent the same series.
- `results` is empty and `source_errors` is populated when all sources fail.
- Does not require a `Comic` row to exist; this is purely a live Suwayomi query.

---

## Requests (Comics)

### `POST /api/requests`

Track a new comic. Triggers source selection and enqueues all available chapter downloads.

**Request Body**

```json
{
  "primary_title": "One Piece",
  "library_title": "One Piece",
  "cover_url": "https://source1-url/cover.jpg",
  "poll_override_days": 7.0,
  "upgrade_override_days": null,
  "aliases": ["ワンピース", "One Piece (Viz)"]
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `primary_title` | string | yes | Display name for the comic in the Otaki UI |
| `library_title` | string | no | Name used for the library folder path and `ComicInfo.xml` `<Series>` tag. Defaults to `primary_title` if omitted. |
| `cover_url` | string \| null | no | Cover image URL; downloaded and stored at request time. Injected as `cover.{ext}` into each chapter CBZ during relocation. |
| `poll_override_days` | float \| null | no | Days between new-chapter polls; `null` = use `DEFAULT_POLL_DAYS` (default 7) |
| `upgrade_override_days` | float \| null | no | Days between upgrade checks; `null` = use `DEFAULT_POLL_DAYS` |
| `aliases` | string[] | no | Alternative titles for this comic. Saved as `ComicAlias` rows and used during source searches to find the comic under its alternative names. |

**Response `201`**

```json
{
  "id": 1,
  "title": "One Piece",
  "library_title": "One Piece",
  "cover_url": null,
  "status": "tracking",
  "poll_override_days": 7.0,
  "upgrade_override_days": null,
  "next_poll_at": "2025-03-22T09:00:00Z",
  "next_upgrade_check_at": "2025-03-22T09:00:00Z",
  "last_upgrade_check_at": null,
  "created_at": "2025-03-15T09:00:00Z",
  "aliases": [
    { "id": 1, "title": "ワンピース" }
  ],
  "source_errors": [
    { "source_name": "BrokenSource", "reason": "connection timed out" }
  ]
}
```

`source_errors` is an empty array on full success. A non-empty array means one or more sources could not be reached during chapter discovery — the comic was still created and chapters from reachable sources were enqueued. Call `POST /api/requests/{id}/discover` to retry failed sources.

**Side Effects**
1. Creates a `Comic` row with `title = primary_title`.
2. Creates `ComicAlias` rows for each entry in `aliases`.
3. Calls `source_selector.build_chapter_source_map()` — searches all enabled sources using `primary_title` and all alias titles, assigning each chapter to the highest-priority source that has it.
4. Calls `suwayomi.fetch_chapters()` per source group.
5. Calls `suwayomi.enqueue_downloads()` grouped by source.
6. Creates one `ChapterAssignment` row per chapter with `download_status=queued`, `is_active=True`.
7. Registers an APScheduler poll job for this comic.

**Error Cases**
- `409 Conflict` — a `Comic` with the same title is already being tracked.
- `422 Unprocessable Entity` — missing or invalid fields.

---

### `GET /api/requests`

List all tracked comics with a summary of download progress.

**Response `200`**

```json
[
  {
    "id": 1,
    "title": "One Piece",
    "library_title": "One Piece",
    "status": "tracking",
    "chapter_counts": {
      "total": 120,
      "done": 118,
      "downloading": 1,
      "queued": 1,
      "failed": 0
    },
    "poll_override_days": 7.0,
    "upgrade_override_days": null,
    "next_poll_at": "2025-03-22T09:00:00Z",
    "next_upgrade_check_at": "2025-03-22T09:00:00Z",
    "last_upgrade_check_at": null
  }
]
```

| Field | Type | Notes |
|---|---|---|
| `chapter_counts` | object | Counts by `download_status`: `total`, `done`, `downloading`, `queued`, `failed` |
| `poll_override_days` | float | Effective poll interval in days |
| `upgrade_override_days` | float \| null | User override for upgrade interval; `null` = use poll interval |
| `next_poll_at` | datetime \| null | When the next new-chapter poll will run |
| `next_upgrade_check_at` | datetime \| null | When the next upgrade check will run |
| `last_upgrade_check_at` | datetime \| null | When upgrade checks last ran |

---

### `GET /api/requests/{id}`

Full detail for one comic: all chapter assignments with download and relocation status.

**Path Parameters**

| Name | Type | Description |
|---|---|---|
| `id` | int | Comic ID |

**Response `200`**

```json
{
  "id": 1,
  "title": "One Piece",
  "library_title": "One Piece",
  "cover_url": null,
  "status": "tracking",
  "poll_override_days": 7.0,
  "upgrade_override_days": null,
  "next_poll_at": "2025-03-22T09:00:00Z",
  "next_upgrade_check_at": "2025-03-22T09:00:00Z",
  "last_upgrade_check_at": "2025-03-15T10:00:00Z",
  "created_at": "2025-03-15T09:00:00Z",
  "aliases": [
    { "id": 1, "title": "ワンピース" }
  ],
  "chapters": [
    {
      "assignment_id": 55,
      "chapter_number": 12.5,
      "volume_number": 2,
      "source_id": 2,
      "source_name": "MangaDex",
      "download_status": "done",
      "is_active": true,
      "downloaded_at": "2025-03-15T09:30:00Z",
      "library_path": "/library/One Piece/One Piece - Ch.0012.5.cbz",
      "relocation_status": "done"
    }
  ]
}
```

**Notes**
- `chapters` is ordered by `chapter_number` ascending. All assignments are returned regardless of `is_active`.
- `library_path` is `null` until relocation completes.

**Error Cases**
- `404 Not Found` — no comic with this ID.

---

### `POST /api/requests/{id}/discover`

Re-run source discovery for a comic and queue any chapters not yet assigned. Safe to call at any time — only creates assignments for chapter numbers not already tracked with `is_active=True`. Intended for comics that ended up with 0 (or partial) assignments due to a connectivity failure at request time.

**Path Parameters**

| Name | Type | Description |
|---|---|---|
| `id` | int | Comic ID |

**Response `200`**

```json
{
  "new_chapters": 3,
  "source_errors": [
    { "source_name": "BrokenSource", "reason": "connection timed out" }
  ]
}
```

| Field | Type | Notes |
|---|---|---|
| `new_chapters` | int | Number of new `ChapterAssignment` rows created |
| `source_errors` | array | Sources that could not be reached during this discovery run |

**Error Cases**
- `404 Not Found` — no comic with this ID.

---

### `DELETE /api/requests/{id}`

Stop tracking a comic. Removes APScheduler jobs, all `ChapterAssignment` rows, and the `Comic` row. Optionally deletes library files.

**Path Parameters**

| Name | Type | Description |
|---|---|---|
| `id` | int | Comic ID |

**Query Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `delete_files` | bool | `false` | If `true`, deletes any files referenced by `library_path` on assignments |

**Response `204 No Content`**

**Error Cases**
- `404 Not Found` — no comic with this ID.

---

### `GET /api/requests/{id}/cover`

Serves the comic's stored cover image.

**Response `200`** — image file (`image/jpeg` or `image/png` depending on stored format).

**Error Cases**
- `404` — no comic with this ID, or no cover has been set.

---

### `POST /api/requests/{id}/cover`

Set or replace the cover image for a comic. Accepts either a URL to download from or a direct file upload.

**Option A — URL** (`application/json`):

```json
{ "url": "https://source-url/cover.jpg" }
```

**Option B — Upload** (`multipart/form-data`):

| Field | Type | Description |
|---|---|---|
| `file` | image file | PNG or JPG cover image |

**Response `200`**

```json
{ "cover_url": "/api/requests/1/cover" }
```

**Side Effects**
- Downloads or saves the image to `COVERS_PATH/{comic_id}.{ext}`, replacing any existing cover.
- All future chapter downloads will have the new cover injected as `cover.png`. Already-relocated chapters are **not** retroactively updated — use `POST /api/quality/{assignment_id}/relocate` to re-process individual chapters if needed.

**Error Cases**
- `404` — no comic with this ID.
- `415 Unsupported Media Type` — file is not a recognised image format.

---

### `DELETE /api/requests/{id}/cover`

Remove the cover image. Future chapter CBZs will not have `cover.png` injected.

**Response `204 No Content`**

---

### `GET /api/requests/{id}/aliases`

List all aliases for a comic.

**Response `200`**

```json
[
  { "id": 1, "title": "ワンピース" },
  { "id": 2, "title": "One Piece (Viz)" }
]
```

---

### `POST /api/requests/{id}/aliases`

Add a new alias to a comic. The alias title is used as a fallback search query when `source_selector` searches for this comic on sources.

**Request Body**

```json
{ "title": "ワンピース" }
```

**Response `201`**

```json
{ "id": 3, "title": "ワンピース" }
```

**Error Cases**
- `404 Not Found` — no comic with this ID.

---

### `DELETE /api/requests/{id}/aliases/{alias_id}`

Remove an alias from a comic.

**Response `204 No Content`**

**Error Cases**
- `404 Not Found` — alias does not exist or does not belong to this comic.

---

## Settings

### `GET /api/settings`

Return the current application settings. Any authenticated user may call this endpoint.

**Response `200`**

```json
{
  "suwayomi_url": "https://suwayomi.example.com",
  "suwayomi_username": "admin",
  "suwayomi_password": "**masked**",
  "suwayomi_download_path": "/data/suwayomi/downloads",
  "library_path": "/data/library",
  "default_poll_days": 7,
  "chapter_naming_format": "{title}/{title} - Ch.{chapter}.cbz",
  "relocation_strategy": "auto"
}
```

| Field | Type | Notes |
|---|---|---|
| `suwayomi_url` | string \| null | Suwayomi server URL |
| `suwayomi_username` | string \| null | Suwayomi login username |
| `suwayomi_password` | `"**masked**"` \| null | `"**masked**"` if a password is set; `null` if unset |
| `suwayomi_download_path` | string \| null | Suwayomi's download staging directory |
| `library_path` | string \| null | Final library directory |
| `default_poll_days` | int | Default poll interval in days |
| `chapter_naming_format` | string | Template for chapter file paths |
| `relocation_strategy` | string | `"auto"` / `"hardlink"` / `"copy"` / `"move"` |

**Error Cases**
- `401 Unauthorized` — missing or invalid token.

---

### `PATCH /api/settings`

Update one or more settings. All fields are optional; omitted fields are left unchanged. Any authenticated user may call this endpoint.

**Request Body** — all fields optional:

```json
{
  "suwayomi_url": "https://suwayomi.example.com",
  "suwayomi_username": "admin",
  "suwayomi_password": "newpassword",
  "suwayomi_download_path": "/data/suwayomi/downloads",
  "library_path": "/data/library",
  "default_poll_days": 14,
  "chapter_naming_format": "{title}/{title} - Ch.{chapter}.cbz",
  "relocation_strategy": "hardlink"
}
```

| Field | Type | Notes |
|---|---|---|
| `suwayomi_url` | string \| null | New Suwayomi URL |
| `suwayomi_username` | string \| null | New username |
| `suwayomi_password` | string \| null | New password; `null` = leave unchanged |
| `suwayomi_download_path` | string \| null | Must be an existing directory |
| `library_path` | string \| null | Must be an existing directory |
| `default_poll_days` | int \| null | New default poll interval |
| `chapter_naming_format` | string \| null | New naming format string |
| `relocation_strategy` | `"auto"` \| `"hardlink"` \| `"copy"` \| `"move"` \| null | New relocation strategy |

**Response `200`** — same schema as `GET /api/settings`, with the updated values (password still masked).

**Behaviour**
- If any of `suwayomi_url`, `suwayomi_username`, or `suwayomi_password` is provided, Otaki pings Suwayomi with the resulting credentials before saving. If connectivity fails, the request is rejected and no settings are changed.
- Path fields (`suwayomi_download_path`, `library_path`) are validated to be existing directories before saving.
- Values are persisted to `.env` and applied to the in-memory `settings` singleton immediately.

**Error Cases**
- `400 Bad Request` — Suwayomi ping failed (when connection fields are provided), or a path field is not a valid directory.
- `401 Unauthorized` — missing or invalid token.
- `422 Unprocessable Entity` — invalid `relocation_strategy` value.

---

## Sources

### `GET /api/sources`

List all configured sources in priority order.

**Response `200`**

```json
[
  {
    "id": 1,
    "suwayomi_source_id": "1998944621602222888",
    "name": "MangaDex",
    "priority": 1,
    "enabled": true,
    "created_at": "2025-03-01T00:00:00Z"
  }
]
```

---

### `POST /api/sources`

Add a new source.

**Request Body**

```json
{
  "suwayomi_source_id": "1998944621602222888",
  "name": "MangaDex",
  "priority": 1,
  "enabled": true
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `suwayomi_source_id` | string | yes | The source ID string from Suwayomi |
| `name` | string | yes | Human-readable label |
| `priority` | int | yes | 1 = highest priority (most preferred) |
| `enabled` | bool | no | Defaults to `true` |

**Response `201`** — the created source object.

**Error Cases**
- `409 Conflict` — `suwayomi_source_id` already exists.

---

### `PATCH /api/sources/{id}`

Update a source (e.g. change priority or toggle enabled).

**Request Body** — all fields optional:

```json
{
  "name": "MangaDex EN",
  "priority": 2,
  "enabled": false
}
```

**Response `200`** — the updated source object.

---

### `DELETE /api/sources/{id}`

Remove a source from the priority list.

**Response `204 No Content`**

**Notes**
- Does not affect already-downloaded chapters or existing `ChapterAssignment` rows.
- Comics currently using this source will retain it until an upgrade or manual change.

---

## Watermark Templates

### `POST /api/sources/watermarks`

Upload a sample page and crop coordinates to extract a new watermark template.

**Request** — `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | image file | yes | Full page image containing the watermark (PNG/JPG) |
| `name` | string | yes | Identifier for this template |
| `x` | int | yes | Left edge of crop region (pixels) |
| `y` | int | yes | Top edge of crop region (pixels) |
| `w` | int | yes | Width of crop region (pixels) |
| `h` | int | yes | Height of crop region (pixels) |
| `source_id` | int | no | Associate with a specific source |
| `match_threshold` | float | no | Detection threshold 0.0–1.0; defaults to `0.8` |

**Response `201`**

```json
{
  "id": 3,
  "name": "MangaDex Logo",
  "source_id": 1,
  "file_path": "mangadex_logo.png",
  "match_threshold": 0.8,
  "enabled": true
}
```

**Side Effects**
- Saves cropped region as PNG to `WATERMARKS_PATH/{name}.png`.
- Inserts a `WatermarkTemplate` row.
- Invalidates the in-memory template cache in `quality_scanner` so the new template is used immediately.

**Notes**
- The crop coordinates are relative to the uploaded image, not to the original manga page dimensions.
- If a file already exists at the target path, the upload will be rejected with `409`.

---

### `GET /api/sources/watermarks`

List all watermark templates.

**Response `200`** — array of template objects (same schema as `POST` response).

---

### `DELETE /api/sources/watermarks/{id}`

Remove a watermark template. Deletes the PNG file and the DB row.

**Response `204 No Content`**

**Notes**
- Does not retroactively change existing `QualityScan` records that referenced this template.

---

## Quality

### `GET /api/quality/{comic_id}`

All quality scan results for a comic, grouped by chapter.

**Path Parameters**

| Name | Type | Description |
|---|---|---|
| `comic_id` | int | Comic ID |

**Response `200`**

```json
[
  {
    "chapter_number": 1.0,
    "assignment_id": 10,
    "scan": {
      "id": 5,
      "scanned_at": "2025-03-15T09:31:00Z",
      "watermark_count": 1,
      "watermark_templates_matched": [3],
      "has_header": false,
      "has_footer": true,
      "severity": "moderate",
      "auto_fixed": true
    }
  }
]
```

**Notes**
- Only active assignments (`is_active=true`) are returned.
- `scan` is `null` for chapters not yet scanned.

---

### `POST /api/quality/{assignment_id}/rescan`

Re-run the quality scanner on an existing downloaded chapter.

**Path Parameters**

| Name | Type | Description |
|---|---|---|
| `assignment_id` | int | ChapterAssignment ID |

**Response `200`** — the new `QualityScan` object.

**Notes**
- Requires `download_status=done` and the CBZ file to exist on disk.
- Creates a new `QualityScan` row; does not delete the previous one.
- Does **not** automatically trigger auto-fix or relocation.

**Error Cases**
- `404` — assignment not found.
- `409` — chapter is not in `done` state or CBZ file is missing.

---

### `POST /api/quality/{assignment_id}/autofix`

Manually run the image processor to crop banners from a chapter.

**Response `200`**

```json
{
  "assignment_id": 10,
  "fixed": true,
  "backup_path": "/suwayomi/downloads/One Piece/Ch.001.cbz.orig"
}
```

**Notes**
- Requires a `QualityScan` row to exist (so the scanner knows what to crop).
- Renames the original CBZ to `*.cbz.orig` before writing the cropped version.
- Sets `quality_scan.auto_fixed=true` on the associated scan row.
- If `auto_fixed` is already `true`, this is a no-op and returns `fixed: false`.

**Error Cases**
- `404` — assignment not found.
- `409` — no scan result exists; run `/rescan` first.

---

### `POST /api/quality/{assignment_id}/relocate`

Manually re-trigger relocation for a settled chapter.

**Response `200`**

```json
{
  "assignment_id": 10,
  "library_path": "/library/One Piece/One Piece - Ch.0001.0.cbz",
  "relocation_status": "done"
}
```

**Notes**
- Use this if relocation previously failed (`relocation_status=failed`) or was skipped.
- If the chapter is already relocated (`relocation_status=done`), this is a no-op.
- Uses the same hardlink/copy logic as automatic relocation.

**Error Cases**
- `404` — assignment not found.
- `409` — chapter `download_status` is not `done`.

---

## Common Types

### `Severity`
```
"clean"    – no watermarks or banners detected
"minor"    – 1 watermark, no banners
"moderate" – watermarks or a banner on one end
"severe"   – watermarks and banners on both ends
```

### `DownloadStatus`
```
"queued"       – waiting in Suwayomi's download queue
"downloading"  – actively downloading
"done"         – download complete; file present on disk
"failed"       – download failed; may be retried by Suwayomi
```

### `RelocationStatus`
```
"pending"  – waiting to be relocated (not yet settled)
"done"     – file moved/linked to library path
"failed"   – relocation attempted but errored
"skipped"  – relocation was not applicable (e.g. chapter superseded by upgrade)
```

### `ComicStatus`
```
"tracking"  – ongoing series; new chapters will be downloaded automatically
"complete"  – series finished; no further updates expected
```

---

## Error Responses

All errors return a JSON body:

```json
{
  "detail": "Comic with this title is already being tracked."
}
```

| Status | Meaning |
|---|---|
| `400 Bad Request` | Malformed request body |
| `401 Unauthorized` | Missing, invalid, or expired session token |
| `404 Not Found` | Resource does not exist |
| `409 Conflict` | State conflict (duplicate, wrong status, etc.) |
| `422 Unprocessable Entity` | Validation error (missing required fields, wrong types) |
| `503 Service Unavailable` | Setup not complete, or Suwayomi is unreachable |

---

## Limitations

- **No pagination** — `GET /api/requests` and `GET /api/quality/{comic_id}` return all rows. For personal use this is acceptable; at large scale (thousands of tracked titles) this will become slow.
- **No real-time push** — the frontend polls via TanStack Query; there is no WebSocket or SSE endpoint for live UI updates beyond what polling provides.
- **Single Suwayomi instance** — only one `SUWAYOMI_URL` is supported. Multiple Suwayomi instances require separate deployments.
- **Filesystem coupling** — image processing and relocation require this app to share the same download path as Suwayomi (Docker volume or same host). Remote or NFS-mounted paths may cause relocation to fall back to the slower copy+delete path.
- **CBZ only** — the scanner and image processor assume Suwayomi downloads in CBZ format. Other archive formats (CBR, PDF) are not supported.
- **First/last page scanning only** — the quality scanner checks only the first and last images in a CBZ. Per-page watermarks on inner pages are not detected.
- **Upgrade replaces, does not merge** — when a chapter is upgraded to a better source, the old file is replaced entirely. There is no diff or partial-page merge.
