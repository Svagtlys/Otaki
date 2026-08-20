# Design: Fix Continuous Subscription Fallback Poll

**Date:** 2026-08-20
**Issue:** #200 — bug(download-listener): continuous subscription error always falls back to poll
**Branch:** fix/continuous-subscription-fallback-poll
**PR:** https://github.com/Svagtlys/Otaki/pull/203

## Problem

The download listener's WebSocket subscription to Suwayomi's `downloadStatusChanged` repeatedly fails with `TransportConnectionFailed('Connect failed')`, causing the listener to fall back to polling indefinitely.

### Root Causes

1. **WebSocket subprotocol mismatch** — The code uses `graphql-transport-ws` (the newer "Apollo Router" protocol) but Suwayomi's GraphQL server implements the older Apollo `graphql-ws` protocol. The `graphql-transport-ws` protocol sends `type=start` messages which Suwayomi rejects as unknown operations.

2. **Subscription query mismatch** — The current query structure differs from what Suwayomi expects:
   - Missing `omittedUpdates` and `state` fields at the `downloadStatusChanged` level
   - Variables missing `maxUpdates` parameter

## Solution

### 1. Change WebSocket Subprotocol

Change `subprotocols=["graphql-transport-ws"]` to `subprotocols=["graphql-ws"]` in [`WebsocketsTransport`](backend/app/services/suwayomi.py:264).

### 2. Update Subscription Query

Replace the current query with the Suwayomi-compatible schema. Only `displayName` is needed (used for `source_display_name` in logging and file relocation):

```graphql
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
```

Variables: `{"input": {"maxUpdates": 50}}`

### 3. Handle Response Format

Suwayomi's Apollo protocol returns events wrapped in `{"type": "next", "id": "...", "payload": {"data": {...}}}`. The `gql` library's `WebsocketsTransport` handles unwrapping. The parsed data shape per message:

```json
{
  "omittedUpdates": false,
  "state": "STARTED",
  "initial": null,
  "updates": [
    {
      "type": "FINISHED",
      "download": {
        "chapter": {"id": 73910, "name": "Ep. 51"},
        "manga": {"title": "Absolute Sword Sense", "source": {"displayName": "Webtoons.com (EN)"}}
      }
    }
  ]
}
```

The `updates` array can contain multiple events per message. Filter for `FINISHED` and `ERROR` types (ignore `PROGRESS`).

## Files Changed

| File | Change |
|------|--------|
| `backend/app/services/suwayomi.py` | Fix subprotocol, query, variables, response parsing |
| `backend/tests/test_suwayomi.py` | Update subscription tests if needed |

## Testing

1. **Subscription connects successfully** — WebSocket connects with `graphql-ws` protocol
2. **Subscription receives FINISHED events** — Events are parsed and yielded correctly
3. **Subscription receives ERROR events** — ERROR events are parsed and yielded correctly
4. **Source display name extracted** — `source.displayName` is correctly yielded from subscription payload

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| `gql` library handles Apollo protocol differently | Test with real Suwayomi instance first |
| Response parsing breaks existing callers | Maintain same yield signature `(event_type, chapter_id, chapter_name, manga_title, source_display_name)` |
| Multiple updates per message | Iterate `updates` array and yield each matching event |

## Rollback

If the subscription still fails after fixes, the existing polling fallback handles graceful degradation.
