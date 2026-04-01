# Otaki

> **LLM assistance** — this project uses LLM coding assistants during development, following the [contribution guidelines](docs/CONTRIBUTING.md#llm-assistance). All generated code and content is human-reviewed before commit.

A comic/manga request manager built on top of [Suwayomi-Server](https://github.com/Suwayomi/Suwayomi-Server). Search for titles across multiple sources, request downloads, and let Otaki handle source selection, automatic upgrades, metadata injection, and relocation to your final library.

---

## What It Does

1. **Configure sources** — rank your Suwayomi extensions by priority in the Sources page. Priority 1 is most preferred.
2. **Search and request** — search for a title across all sources at once. Otaki assigns each chapter to the highest-priority source that has it — chapters in the same series can come from different sources. Supports multi-alias titles (e.g. the same series under different names on different sources).
3. **Smart polling** — Otaki infers each comic's release cadence from its chapter history and polls on a matching schedule. Per-comic overrides are available. When a new chapter is found, it downloads from the best available source.
4. **Source upgrades** — on a regular schedule, Otaki checks whether a higher-priority source has picked up chapters currently on a lower-priority one. If so, it re-downloads and replaces automatically.
5. **Metadata** — each chapter CBZ gets a `ComicInfo.xml` update (`<Series>`, `<Number>`, `<Volume>`) and a `cover.png` injected automatically. Library title is configurable separately from the display title.
6. **Relocation** — once a chapter is settled, Otaki moves it to your final library folder with a configurable naming format — similar to how Radarr/Sonarr manage media.

---

## Roadmap

| Release | Focus | Status |
|---|---|---|
| **1.0** | MVP — download pipeline, source upgrades, basic auth | Released |
| **1.1** | Metadata — `ComicInfo.xml`, covers, multi-alias, cadence inference, per-comic schedules | Released |
| **1.2** | Scale — local source overrides, pagination, library import | Planned |
| **1.3** | Quality — watermark/banner detection, auto-fix, image order checking | Planned |
| **1.4** | Auth — roles, SSO, user management | Planned |

Full details in [docs/ROADMAP.md](docs/ROADMAP.md).

---

## Deploy

> **Prerequisites:** Docker + Docker Compose, and a running [Suwayomi-Server](https://github.com/Suwayomi/Suwayomi-Server) instance.

Download the deployment files:

```bash
mkdir otaki && cd otaki
curl -fsSL https://raw.githubusercontent.com/Svagtlys/Otaki/main/deploy/docker-compose.yml -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/Svagtlys/Otaki/main/deploy/nginx.conf -o nginx.conf
mkdir -p data suwayomi library covers watermarks
curl -fsSL https://raw.githubusercontent.com/Svagtlys/Otaki/main/deploy/.env.example -o data/.env
```

Edit `data/.env` — at minimum, set these two values:

```bash
SUWAYOMI_URL=http://<your-suwayomi-host>:4567
SECRET_KEY=<output of: openssl rand -hex 32>
```

Start Otaki:

```bash
UID=$(id -u) GID=$(id -g) docker compose up -d
```

Open `http://localhost` — the setup wizard will guide you through source configuration on first run.

The `mkdir -p` step above creates the host directories as your user before Docker mounts them — this ensures the backend process has write access. All path variables (`LIBRARY_PATH`, `SUWAYOMI_DOWNLOAD_PATH`, etc.) are pre-configured by `docker-compose.yml`.

To update to a new version: edit the image tags in `docker-compose.yml`, then run `docker compose pull && docker compose up -d`.

---

## For Developers (local build)

```bash
git clone https://github.com/Svagtlys/Otaki.git && cd Otaki
cp .env.example .env
# Minimum required in .env:
#   SECRET_KEY=<random string>
#   SUWAYOMI_URL=http://suwayomi:4567   # if using the bundled suwayomi service
UID=$(id -u) GID=$(id -g) docker compose -f docker/docker-compose.yml up
```

---

## Configuration

Key `.env` values:

| Variable | Description |
|---|---|
| `SUWAYOMI_URL` | URL of your Suwayomi-Server instance |
| `SUWAYOMI_DOWNLOAD_PATH` | Suwayomi's download folder (must be a shared volume) |
| `LIBRARY_PATH` | Final destination for settled chapters |
| `CHAPTER_NAMING_FORMAT` | Naming template, e.g. `{title}/{title} - Ch.{chapter:04.1f}.cbz` |
| `DEFAULT_POLL_DAYS` | Fallback poll interval in days — used when cadence cannot be inferred from chapter history |

Available naming tokens: `{title}`, `{chapter}`, `{volume}`, `{year}`, `{source}`

---

## Developer Docs

- [docs/PLAN.md](docs/PLAN.md) — full design: data model, workflows, tech stack
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — file-by-file breakdown of every service and worker
- [docs/API.md](docs/API.md) — all API endpoints with request/response schemas
- [docs/FLOWS.md](docs/FLOWS.md) — system and UI flow diagrams
- [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) — commit conventions, branching, LLM guidelines
- [CLAUDE.md](CLAUDE.md) — quick-start context for AI assistants
