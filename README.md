# Otaki

> **Work in progress** — currently building towards 1.0 (MVP). See the [roadmap](docs/ROADMAP.md) for what's planned and what's coming.

> **LLM assistance** — this project uses LLM coding assistants during development, following the [contribution guidelines](docs/CONTRIBUTING.md#llm-assistance). All generated code and content is human-reviewed before commit.

A comic/manga request manager built on top of [Suwayomi-Server](https://github.com/Suwayomi/Suwayomi-Server). Search for titles across multiple sources, request downloads, and let Otaki handle source selection, automatic upgrades, and relocation to your final library.

---

## What It Does (1.0 MVP)

1. **Configure sources** — rank your Suwayomi extensions by priority in the Sources page. Priority 1 is most preferred.
2. **Search and request** — search for a title across all sources at once. Otaki assigns each chapter to the highest-priority source that has it — chapters in the same series can come from different sources.
3. **Polling** — Otaki checks for new chapters on a configurable schedule. When a new chapter is found, it downloads from the best available source.
4. **Source upgrades** — on a regular schedule, Otaki checks whether a higher-priority source has picked up chapters currently on a lower-priority one. If so, it re-downloads and replaces automatically.
5. **Relocation** — once a chapter is settled, Otaki moves it to your final library folder with a configurable naming format — similar to how Radarr/Sonarr manage media.

---

## Roadmap

| Release | Focus |
|---|---|
| **1.0** | MVP — download pipeline, source upgrades, basic auth |
| **1.1** | Metadata — `ComicInfo.xml`, covers, multi-alias support, library title |
| **1.2** | Intelligence — cadence inference, per-comic schedules, notifications |
| **1.3** | Scale — local source overrides, pagination, library import |
| **1.4** | Quality — watermark/banner detection, auto-fix, image order checking |
| **1.5** | Auth — roles, SSO, user management |

Full details in [docs/ROADMAP.md](docs/ROADMAP.md).

---

## Setup

> **Prerequisites:** Docker + Docker Compose, a running Suwayomi-Server instance.

```bash
cp .env.example .env
# Edit .env — set SUWAYOMI_URL, SUWAYOMI_DOWNLOAD_PATH, LIBRARY_PATH
docker compose up
```

Open `http://localhost:5173` — the setup wizard will guide you through connecting Suwayomi and configuring source priority on first run.

---

## Configuration

Key `.env` values:

| Variable | Description |
|---|---|
| `SUWAYOMI_URL` | URL of your Suwayomi-Server instance |
| `SUWAYOMI_DOWNLOAD_PATH` | Suwayomi's download folder (must be a shared volume) |
| `LIBRARY_PATH` | Final destination for settled chapters |
| `CHAPTER_NAMING_FORMAT` | Naming template, e.g. `{title}/{title} - Ch.{chapter:04.1f}.cbz` |
| `DEFAULT_POLL_DAYS` | How often to check for new chapters (in days) |

Available naming tokens: `{title}`, `{chapter}`, `{volume}`, `{year}`, `{source}`

---

## For Developers

- [docs/PLAN.md](docs/PLAN.md) — full design: data model, workflows, tech stack
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — file-by-file breakdown of every service and worker
- [docs/API.md](docs/API.md) — all API endpoints with request/response schemas
- [docs/FLOWS.md](docs/FLOWS.md) — system and UI flow diagrams
- [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) — commit conventions, branching, LLM guidelines
- [CLAUDE.md](CLAUDE.md) — quick-start context for AI assistants
