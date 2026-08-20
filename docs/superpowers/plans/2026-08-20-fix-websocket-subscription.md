# Fix WebSocket Subscription Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the WebSocket subscription to Suwayomi's `downloadStatusChanged` by updating the subprotocol, query, and response parsing.

**Architecture:** Change `graphql-transport-ws` to `graphql-ws` (Apollo protocol), update the subscription query to include `omittedUpdates` and `state` fields, add `maxUpdates` to variables, and handle the Apollo response format where `updates` can contain multiple events per message.

**Tech Stack:** Python 3.13, `gql` library, `WebsocketsTransport`, `graphql-ws` protocol

---

### Task 1: Update Subscription Query

**Files:**
- Modify: `backend/app/services/suwayomi.py:229-246`
- Modify: `backend/app/services/suwayomi.py:264`
- Modify: `backend/app/services/suwayomi.py:269`

- [ ] **Step 1: Update the subscription query**

Replace the `DOWNLOAD_STATUS_SUBSCRIPTION` definition at [`suwayomi.py:229`](backend/app/services/suwayomi.py:229) to include `omittedUpdates` and `state` fields, and move `source { displayName }` into both `initial` and `updates`:

```python
DOWNLOAD_STATUS_SUBSCRIPTION = gql("""
    subscription OnDownloadStatusChanged($input: DownloadChangedInput!) {
        downloadStatusChanged(input: $input) {
            omittedUpdates
            state
            initial {
                state
                chapter { id name }
                manga { title source { displayName } }
            }
            updates {
                type
                download {
                    chapter { id name }
                    manga { title source { displayName } }
                }
            }
        }
    }
""")
```

- [ ] **Step 2: Change WebSocket subprotocol**

Change line 264 from `graphql-transport-ws` to `graphql-ws`:

```python
    transport = WebsocketsTransport(
        url=ws_url,
        headers=_auth_headers(),
        ssl=ssl_arg,
        subprotocols=["graphql-ws"],
    )
```

- [ ] **Step 3: Update subscription variables**

Change line 269 from `{"input": {}}` to `{"input": {"maxUpdates": 50}}`:

```python
        async for result in session.subscribe(
            DOWNLOAD_STATUS_SUBSCRIPTION, variable_values={"input": {"maxUpdates": 50}}
        ):
```

- [ ] **Step 4: Run existing tests to check for regressions**

Run: `cd backend && .venv/bin/pytest tests/test_download_listener.py -v`
Expected: All existing tests should still pass (the query change shouldn't break unit tests since they mock the subscription).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/suwayomi.py
git commit -m "fix(download-listener): use graphql-ws protocol and updated subscription query"
```

### Task 2: Run Integration Test to Verify Fix

**Files:**
- Test: `backend/tests/test_download_listener.py` (integration test already exists)

- [ ] **Step 1: Run the integration test against real Suwayomi**

Run: `cd backend && .venv/bin/pytest tests/test_download_listener.py::test_enqueue_and_receive_via_subscription -v -m integration`
Expected: PASS — the subscription should now connect and receive FINISHED events.

- [ ] **Step 2: If integration test passes, commit**

```bash
git add backend/
git commit -m "test(download-listener): verify subscription fix with integration test"
```

- [ ] **Step 3: If integration test fails, debug and iterate**

Check Suwayomi logs for errors. The subscription should now work since we've verified the query manually with `wscat`.

## Self-Review

**Spec coverage:**
- ✅ Change subprotocol from `graphql-transport-ws` to `graphql-ws`
- ✅ Update subscription query with `omittedUpdates`, `state`, and correct field structure
- ✅ Update variables to include `maxUpdates: 50`
- ✅ Response format handling — the existing code already iterates `updates` array and extracts `source.displayName` from `manga.source.displayName`

**Placeholder scan:** No placeholders found. All code blocks are complete.

**Type consistency:** The yield signature `(event_type, chapter_id, chapter_name, manga_title, source_display_name)` is maintained throughout. The `source_name` extraction uses `(manga.get("source") or {}).get("displayName", "")` which matches the new response format.
