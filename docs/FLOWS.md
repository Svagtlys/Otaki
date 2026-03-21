# Flows

Mermaid diagrams for key UI/UX and logic flows.

---

## 0. First-Time Setup

```mermaid
flowchart TD
    A([Otaki starts]) --> B{SUWAYOMI_URL<br/>configured?}
    B -->|no| C[Show Setup Wizard]
    B -->|yes| D{GET /api/health<br/>Suwayomi reachable?}
    D -->|yes| Z([Normal app — Library page])
    D -->|no| E[Show connection error<br/>with edit option]
    E --> C

    C --> F[Step 1: Enter Suwayomi URL<br/>and credentials<br/>username + password]
    F --> G[Test connection<br/>POST /api/setup/connect]
    G --> H{Connection<br/>successful?}
    H -->|no| I[Show error<br/>wrong URL or credentials]
    I --> F
    H -->|yes| J[Save to config<br/>SUWAYOMI_URL + credentials]

    J --> K[Step 2: Load installed sources<br/>GET /api/setup/sources<br/>fetches from Suwayomi]
    K --> L{Any sources<br/>installed in Suwayomi?}
    L -->|no| M[Prompt: install at least<br/>one source in Suwayomi first<br/>link to Suwayomi UI]
    M --> K
    L -->|yes| N[Show source list<br/>drag to set priority order<br/>1 = most preferred]
    N --> O[User reorders and confirms]
    O --> P[POST /api/setup/sources<br/>save priority list to DB]

    P --> Q[Step 3: Configure paths<br/>SUWAYOMI_DOWNLOAD_PATH<br/>LIBRARY_PATH]
    Q --> R[Save paths to config]
    R --> S[Setup complete]
    S --> Z
```

---

## 1. UI Navigation

```mermaid
flowchart TD
    Login([Login Page])
    Search([Search Page])
    Library([Library Page])
    Comic([Comic Detail Page])
    Sources([Sources Page])
    Settings([Settings Page])
    Users([User Management Page<br/>admin only])

    Login -->|"authenticated"| Library

    Search -->|"request submitted<br/>requires: request_comics"| Library
    Library -->|"click comic row"| Comic
    Comic -->|"rescan / autofix / relocate<br/>requires: request_upgrades"| Comic
    Comic -->|"edit cadence override<br/>requires: manage_cadence"| Comic
    Comic -->|"edit local source priority<br/>requires: local_source_override"| Comic
    Library -->|"nav"| Sources
    Library -->|"nav"| Search
    Search -->|"nav"| Library

    Sources -->|"add watermark template<br/>requires: manage_sources"| Sources
    Sources -->|"drag reorder global priority<br/>requires: manage_sources"| Sources

    Library -->|"nav"| Settings
    Settings -->|"Suwayomi URL + credentials<br/>admin only"| Settings
    Settings -->|"Suwayomi download path<br/>admin only"| Settings
    Settings -->|"library path<br/>admin only"| Settings
    Settings -->|"chapter naming format<br/>admin only"| Settings
    Settings -->|"auto-fix banners toggle<br/>admin only"| Settings
    Settings -->|"SSO provider config<br/>admin only"| Settings
    Settings -->|"nav to user management<br/>admin only"| Users
    Users -->|"add / edit / remove users<br/>assign roles"| Users
    Users -->|"back"| Settings
```

---

## 1a. Authentication Flow

```mermaid
flowchart TD
    A([User visits Otaki]) --> B{Session<br/>valid?}
    B -->|yes| Z([Normal app])
    B -->|no| C[Login Page]

    C --> D{Login method}
    D -->|Local| E[Enter username + password]
    E --> F[POST /api/auth/login]
    F --> G{Credentials<br/>valid?}
    G -->|no| H[Show error]
    H --> E
    G -->|yes| I[Issue session token]
    I --> Z

    D -->|SSO| J[Redirect to provider<br/>Google / GitHub / OIDC]
    J --> K[Provider authenticates user]
    K --> L[Callback: GET /api/auth/callback]
    L --> M{User exists<br/>in DB?}
    M -->|yes| I
    M -->|no — first SSO login| N{Auto-provision<br/>enabled?}
    N -->|yes| O[Create user with<br/>default role: reader]
    O --> I
    N -->|no| P[Show access denied<br/>admin must add user first]
```

---

## 1b. Permission Roles

```mermaid
flowchart TD
    subgraph Reader
        V1[View library]
        V2[View quality scans]
        V3[View chapter status]
    end

    subgraph Requestor
        C1[All Reader permissions]
        C2[Request new comics]
        C3[Request chapter upgrades]
        C4[Comic-local source overrides]
    end

    subgraph Admin
        A1[All Requestor permissions]
        A2[Change global source priority]
        A3[Manage watermark templates]
        A4[Override poll cadence per comic]
        A5[Override upgrade cadence per comic]
        A6[Manage users and roles]
        A7[Configure Suwayomi connection]
        A8[Configure paths]
        A9[Configure SSO providers]
    end

    Reader --> Requestor --> Admin
```

---

## 2. Request Submission Flow

```mermaid
flowchart TD
    A[User searches title] --> B[GET /api/search]
    B --> C[Fan out to all enabled sources in parallel]
    C --> D[Return all results with cover image + source label<br/>no deduplication]
    D --> E[User selects one or more results<br/>that represent the same series]
    E --> E2[User sets preferred display title<br/>and library title]
    E2 --> E3[User picks cover from available<br/>source covers or uploads their own]
    E3 --> F[POST /api/requests]
    F --> G[Create Comic row + ComicAlias rows<br/>one alias per selected result]
    G --> H[build_chapter_source_map<br/>search all sources using all aliases]
    H --> I{For each chapter:<br/>best source available?}
    I -->|yes| J[Assign chapter to<br/>highest-priority source that has it]
    I -->|no source has it| K[Skip — recheck on next poll]
    J --> L[Group chapters by source]
    L --> M[addMangaToLibrary + fetchChapterList<br/>per distinct source]
    M --> N[enqueueChapterDownloads per source]
    N --> O[Create ChapterAssignment rows<br/>with chapter_published_at]
    O --> P[infer_cadence from publication dates]
    P --> Q[Set next_poll_at and next_upgrade_check_at]
    Q --> R[Register APScheduler poll + upgrade jobs]
```

---

## 3. Chapter Download Lifecycle

```mermaid
flowchart TD
    A[Otaki calls enqueueChapterDownload<br/>via Suwayomi GraphQL] --> B[Suwayomi executes download<br/>download_listener receives DOWNLOADED event]
    B --> C[chapter_event_handler.handle]
    C --> D[quality_scanner.scan_chapter<br/>first + last page only]
    D --> E[Write QualityScan row]
    E --> F{AUTO_FIX_BANNERS<br/>and has_header/footer?}
    F -->|yes| G[image_processor.crop_chapter<br/>save .orig backup]
    F -->|no| H
    G --> H[file_relocator.relocate<br/>hardlink or copy+delete]
    H --> I{Was this an<br/>upgrade download?}
    I -->|no — regular download| J[Done]
    I -->|yes — upgrade| K{new severity ≤<br/>old severity?}
    K -->|yes| L[replace_in_library atomic swap<br/>flip is_active]
    K -->|no| M[Discard new assignment<br/>keep old]
```

---

## 4. Poll Job — New Chapter Detection

```mermaid
flowchart TD
    A([APScheduler fires poll job<br/>at next_poll_at]) --> B[Fetch chapter list from<br/>all enabled sources]
    B --> C[Compare against known<br/>ChapterAssignment rows]
    C --> D{Any new<br/>chapter numbers?}
    D -->|no| E[Advance next_poll_at<br/>by effective interval]
    D -->|yes| F[For each new chapter:<br/>pick highest-priority source that has it]
    F --> G[addMangaToLibrary if source<br/>not already in Suwayomi]
    G --> H[enqueueChapterDownload]
    H --> I[Create ChapterAssignment row]
    I --> J[Re-run infer_cadence<br/>update inferred_cadence_days]
    J --> E
```

---

## 5. Upgrade Check Job

```mermaid
flowchart TD
    A([APScheduler fires upgrade job<br/>at next_upgrade_check_at]) --> B[find_upgrade_candidates<br/>for all active ChapterAssignments]
    B --> C{Any chapter on a<br/>non-optimal source?}
    C -->|no| D[Advance next_upgrade_check_at]
    C -->|yes| E[For each candidate:<br/>fetch chapter list from better source]
    E --> F{Better source<br/>has the chapter?}
    F -->|no| D
    F -->|yes| G[addMangaToLibrary if needed]
    G --> H[enqueueChapterDownload<br/>from better source]
    H --> I[chapter_event_handler handles<br/>download as upgrade — see Flow 3]
    I --> D
```

---

## 6. Cadence Inference

```mermaid
flowchart TD
    A[N most recent chapters<br/>with chapter_published_at] --> B[Compute all inter-chapter gaps]
    B --> C[Compute initial median gap]
    C --> D[Filter out gaps<br/>> 3× initial median<br/>hiatuses / long breaks]
    D --> E[Compute final median<br/>from filtered gaps]
    E --> F{Fewer than<br/>2 data points?}
    F -->|yes| G[Return null<br/>use 7-day default]
    F -->|no| H[Store in comic.inferred_cadence_days]
    H --> I{poll_override_days set?}
    I -->|yes| J[Use poll_override_days<br/>for next_poll_at]
    I -->|no| K[Use inferred_cadence_days<br/>for next_poll_at]
    H --> L{upgrade_override_days set?}
    L -->|yes| M[Use upgrade_override_days<br/>for next_upgrade_check_at]
    L -->|no| N[Use inferred_cadence_days<br/>for next_upgrade_check_at]
```

---

## 7. Source Upgrade Decision

```mermaid
flowchart TD
    A[Chapter on source<br/>priority N] --> B{Any source with<br/>priority < N<br/>has this chapter?}
    B -->|no| C[Chapter is settled<br/>on best available source]
    B -->|yes| D[Download from<br/>better source]
    D --> E[Scan quality]
    E --> F{new severity<br/>≤ old severity?}
    F -->|yes — equal or better| G[Swap: flip is_active<br/>atomic library replace]
    F -->|no — worse quality| H[Discard<br/>keep original]
    G --> I{Now on<br/>priority 1?}
    I -->|yes| C
    I -->|no| B
```
