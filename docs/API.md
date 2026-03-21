# API Reference

All endpoints are served under `/api`. Requests and responses use JSON unless otherwise noted. The backend is async (FastAPI); all endpoints support concurrent requests.

---

## Table of Contents

- [Search](#search)
- [Requests (Comics)](#requests-comics)
- [Sources](#sources)
- [Watermark Templates](#watermark-templates)
- [Quality](#quality)
- [Common Types](#common-types)
- [Error Responses](#error-responses)
- [Limitations](#limitations)

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
[
  {
    "title": "One Piece",
    "cover_url": "https://...",
    "synopsis": "...",
    "source_id": 1,
    "source_name": "MangaDex",
    "url": "https://source-url/manga/one-piece"
  },
  {
    "title": "ワンピース",
    "cover_url": "https://...",
    "synopsis": "...",
    "source_id": 2,
    "source_name": "MangaPlus",
    "url": "https://source2-url/manga/wan-piisu"
  }
]
```

| Field | Type | Notes |
|---|---|---|
| `title` | string | Title as returned by this source |
| `cover_url` | string \| null | Cover image URL served by Suwayomi |
| `synopsis` | string \| null | Short description, may be empty |
| `source_id` | int | Otaki source ID |
| `source_name` | string | Human-readable source label |
| `url` | string | Source-specific manga URL, passed back when submitting a request |

**Notes**
- Fans out to all enabled sources in parallel; slow sources are waited on up to a timeout.
- No deduplication — the frontend shows all results and lets the user select which ones represent the same series.
- Returns an empty array `[]` if no results are found — never 404.
- Does not require a `Comic` row to exist; this is purely a live Suwayomi query.

---

## Requests (Comics)

### `POST /api/requests`

Track a new comic. Triggers source selection, adds the manga to Suwayomi, and enqueues all available chapter downloads.

**Request Body**

```json
{
  "primary_title": "One Piece",
  "library_title": "One Piece",
  "cover_url": "https://source1-url/cover.jpg",
  "aliases": [
    { "title": "One Piece", "url": "https://source1-url/manga/one-piece" },
    { "title": "ワンピース", "url": "https://source2-url/manga/wan-piisu" }
  ],
  "poll_override_days": null,
  "upgrade_override_days": null
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `primary_title` | string | yes | Display name for the comic in the Otaki UI |
| `library_title` | string | no | Name used for the library folder path and `ComicInfo.xml` `<Series>` tag. Defaults to `primary_title` if omitted. Must be consistent to avoid comic readers splitting one series into multiple. |
| `cover_url` | string \| null | no | URL of the cover image to download and store (typically a `cover_url` from a search result). If omitted, no cover is set — can be added later via `POST /api/requests/{id}/cover`. |
| `aliases` | array | yes | One or more `{title, url}` pairs from search results. Each entry is a known name for this series on a specific source. At least one required. |
| `aliases[].title` | string | yes | Title as returned by that source's search result |
| `aliases[].url` | string | yes | Source-specific manga URL from the search result |
| `poll_override_days` | int \| null | no | Days between new-chapter polls; `null` = use inferred cadence (default 7d until history exists) |
| `upgrade_override_days` | int \| null | no | Days between upgrade checks; `null` = use inferred cadence |

**Response `201`**

```json
{
  "id": 1,
  "title": "One Piece",
  "library_title": "One Piece",
  "cover_url": "/api/requests/1/cover",
  "status": "tracking",
  "inferred_cadence_days": null,
  "poll_override_days": null,
  "upgrade_override_days": null,
  "next_poll_at": "2025-03-22T09:00:00Z",
  "next_upgrade_check_at": "2025-03-22T09:00:00Z",
  "last_upgrade_check_at": null,
  "created_at": "2025-03-15T09:00:00Z"
}
```

**Side Effects**
1. Creates a `Comic` row with `title = primary_title`.
2. Creates one `ComicAlias` row per entry in `aliases`.
3. Calls `source_router.build_chapter_source_map()` — queries all enabled sources using all known aliases and assigns each chapter to the highest-priority source that has it.
4. For each distinct source needed, calls Suwayomi `addMangaToLibrary` + `fetchChapterList`.
5. Calls `enqueueChapterDownloads` grouped by source.
6. Creates one `ChapterAssignment` row per chapter with the assigned source and `download_status=queued`.
7. Registers two APScheduler jobs for this comic: a poll job and an upgrade job, both initialised to fire in `inferred_cadence_days` (default 7 days).

**Error Cases**
- `409 Conflict` — a `Comic` with the same title is already being tracked.
- `422 Unprocessable Entity` — missing or invalid fields.
- `503 Service Unavailable` — Suwayomi is unreachable.

---

### `GET /api/requests`

List all tracked comics with a summary of download progress and worst quality severity.

**Response `200`**

```json
[
  {
    "id": 1,
    "title": "One Piece",
    "status": "tracking",
    "worst_severity": "minor",
    "chapter_counts": {
      "total": 120,
      "done": 118,
      "downloading": 1,
      "queued": 1,
      "failed": 0
    },
    "inferred_cadence_days": 7.0,
    "poll_override_days": null,
    "upgrade_override_days": null,
    "next_poll_at": "2025-03-22T09:00:00Z",
    "next_upgrade_check_at": "2025-03-22T09:00:00Z",
    "last_upgrade_check_at": null
  }
]
```

| Field | Type | Notes |
|---|---|---|
| `worst_severity` | `"clean"` \| `"minor"` \| `"moderate"` \| `"severe"` \| `null` | Worst severity across all scanned chapters; `null` if no scans yet |
| `chapter_counts` | object | Counts by `download_status` |
| `inferred_cadence_days` | float \| null | Inferred release cadence; `null` until enough history |
| `poll_override_days` | int \| null | User override for poll interval |
| `upgrade_override_days` | int \| null | User override for upgrade interval |
| `next_poll_at` | datetime \| null | When the next new-chapter poll will run |
| `next_upgrade_check_at` | datetime \| null | When the next upgrade check will run |
| `last_upgrade_check_at` | datetime \| null | When upgrade checks last ran |

---

### `GET /api/requests/{id}`

Full detail for one comic: all chapters with quality badges and library paths.

**Path Parameters**

| Name | Type | Description |
|---|---|---|
| `id` | int | Comic ID |

**Response `200`**

```json
{
  "id": 1,
  "title": "One Piece",
  "status": "tracking",
  "inferred_cadence_days": 7.0,
  "poll_override_days": null,
  "upgrade_override_days": null,
  "next_poll_at": "2025-03-22T09:00:00Z",
  "next_upgrade_check_at": "2025-03-22T09:00:00Z",
  "last_upgrade_check_at": "2025-03-15T10:00:00Z",
  "created_at": "2025-03-15T09:00:00Z",
  "chapters": [
    {
      "assignment_id": 55,
      "chapter_number": 12.5,
      "volume_number": 2,
      "source": {
        "id": 2,
        "name": "MangaDex"
      },
      "download_status": "done",
      "is_active": true,
      "downloaded_at": "2025-03-15T09:30:00Z",
      "library_path": "/library/One Piece/One Piece - Ch.0012.5.cbz",
      "relocation_status": "done",
      "quality": {
        "scanned_at": "2025-03-15T09:31:00Z",
        "watermark_count": 0,
        "watermark_templates_matched": [],
        "has_header": false,
        "has_footer": false,
        "severity": "clean",
        "auto_fixed": false
      }
    }
  ]
}
```

**Notes**
- `chapters` contains only rows where `is_active=true` by default (the canonical copy per chapter number).
- `quality` is `null` if the chapter has not been scanned yet.
- `library_path` is `null` until relocation completes.

**Error Cases**
- `404 Not Found` — no comic with this ID.

---

### `DELETE /api/requests/{id}`

Stop tracking a comic. Optionally removes library files and the Suwayomi entry.

**Path Parameters**

| Name | Type | Description |
|---|---|---|
| `id` | int | Comic ID |

**Query Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `delete_files` | bool | `false` | If `true`, deletes all files at `library_path` for active assignments |
| `remove_from_suwayomi` | bool | `false` | If `true`, calls Suwayomi `deleteManga` mutation |

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
| `404 Not Found` | Resource does not exist |
| `409 Conflict` | State conflict (duplicate, wrong status, etc.) |
| `422 Unprocessable Entity` | Validation error (missing required fields, wrong types) |
| `503 Service Unavailable` | Suwayomi is unreachable |

---

## Limitations

- **No pagination** — `GET /api/requests` and `GET /api/quality/{comic_id}` return all rows. For personal use this is acceptable; at large scale (thousands of tracked titles) this will become slow.
- **No real-time push** — the frontend polls via TanStack Query; there is no WebSocket or SSE endpoint for live UI updates beyond what polling provides.
- **Single Suwayomi instance** — only one `SUWAYOMI_URL` is supported. Multiple Suwayomi instances require separate deployments.
- **Filesystem coupling** — image processing and relocation require this app to share the same download path as Suwayomi (Docker volume or same host). Remote or NFS-mounted paths may cause relocation to fall back to the slower copy+delete path.
- **CBZ only** — the scanner and image processor assume Suwayomi downloads in CBZ format. Other archive formats (CBR, PDF) are not supported.
- **First/last page scanning only** — the quality scanner checks only the first and last images in a CBZ. Per-page watermarks on inner pages are not detected.
- **Upgrade replaces, does not merge** — when a chapter is upgraded to a better source, the old file is replaced entirely. There is no diff or partial-page merge.
