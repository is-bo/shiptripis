# K7 package A — realtime audit and verdicts (plan §15.1–15.6)

**Base:** `f77ae0e` (K6 L). **Scope:** measure and inspect the realtime path
(Go `chat` + `notification` relays, `pkg/wsproto`, `pkg/redisbus`, the Django
publisher, the Flutter `NotificationSocket` / `LiveUpdates` catch-up), give a
verdict per section, and fix only confirmed defects with a small, clear fix.
Nothing touched Railway, LIVE or any remote.

Related: [K5 client socket lifecycle](../PHASE_K5_MOBILE_PERFORMANCE.md),
[K6 Redis map](../k6-notes/redis.md), [K6 capacity](../k6-notes/capacity.md),
[K6 ws_stats](../k6-notes/reliability-observability.md).

## Verdicts

| § | Measured / inspected | Verdict | Action |
| --- | --- | --- | --- |
| 15.1 Transport | WS is cheap (68 KiB/notification socket, ~7-9 k connects/s per relay, no DB per connect); replay is REST catch-up by design | **Keep WebSocket** (notifications and chat) | none |
| 15.2 Presence | 0.2 SETEX/s per online user; 2,000/s at 10 k users; **no reader exists** | Not material; keep | recommend removing or lengthening later (below) |
| 15.3 Backpressure | slow-consumer drop was silent and counted as delivered; 3 Django channels never subscribed | **2 defects fixed**; one design gap and one tuning note flagged | fixed in this package |
| 15.4 Reconnect storms | 2,000 sockets reconnect in 0.5 s with 0 failures; 8 s outage recovers in 6 s | Go side survives; the **REST catch-up burst on Django** is the real cost | flag: split realtime (K6 T3/T5), catch-up jitter above ~300 online users |
| 15.5 Missed events | resume + every socket connect reconcile inbox, unread, mounted lists, open Deal, open chat (after_id delta) | Recovery is sound | one server-side gap flagged (Redis resubscribe) |
| 15.6 Chat scaling | 1,000-msg thread: 4-6 queries, 4.5-17 ms per page; fan-out ~6 k frames/s paced with 0 loss | No chat bottleneck | none; `unread-count` flagged for Codex |

## Defects fixed

1. **Slow consumers lost events silently and suppressed the push fallback.**
   `wsproto.Conn.Send` dropped a frame when the 64-slot send buffer was full but
   kept the socket open. A client slow enough to fill the buffer, but never slow
   enough to hit the 10 s `WriteTimeout`, never reconnected, so it never ran its
   REST catch-up. `Hub.Send` still counted that socket, so the dispatcher wrote a
   `delivered:<event>:<user>` receipt, and FCM then skipped the push for a
   message that never left the server.
   *Fix:* `Send` now returns `bool`. On overflow it cancels `connCtx`: the
   writer's in-flight write fails, the writer exits and closes the socket, and
   the client reconnects and catches up. Both hubs count only sockets that
   actually queued the frame, so no receipt is written and FCM still fires.
   Tests: `TestSend_DropsWhenBufferFull` (return value plus cancel) and
   `TestConn_SlowConsumerIsDisconnected` (real socket, client stops reading,
   teardown well under `WriteTimeout`). Both were checked to fail without the
   fix (teardown took 10.01 s).
2. **The three I1A arrival channels never reached a live socket.** Django
   publishes `deal.arrival_reported`, `deal.arrival_confirmed` and
   `deal.arrival_declined` (`apps/deals/arrival.py`), and the mobile client
   handles them, but `notification.subscribeChannels` never listed them. The
   inbox row and FCM still landed, so nothing errored. The live refresh simply
   never happened. *Fix:* the channels are now subscribed. A new
   `TestSubscribeChannelsMatchDjango` parses `apps/core/channels.py` and fails on
   any drift in either direction; it was checked to fail with one channel removed.

## 15.1 Notification transport: keep WebSocket

The plan's SSE conditions, checked against the code:

- **Truly one-way:** yes today (both relays read inbound frames only to answer
  pings and drop any envelope). This is the only condition that holds.
- **WS overhead material:** no. The Go notification relay costs 68 KiB per
  socket (K6). It accepts ~7,000-8,500 connects/s on this box with dial p99
  ≤ 37 ms. Each connect costs one local HS256 verify and one Redis SETEX, and no
  Postgres. SSE would still hold one long-lived connection per user through
  Caddy (145 KiB/socket today, the larger share), so the saving is marginal.
- **HTTP/2 serves SSE cleanly:** unproven. The Railway edge proxies to Caddy,
  and Caddy proxies to the relays. SSE needs `flush_interval -1` and survival of
  the edge's idle and buffering behaviour. The WS upgrade path is already proven
  on TEST.
- **Simpler mobile lifecycle:** no. `NotificationSocket` already has one owner,
  jittered backoff, a 20 s client ping for half-open detection, and a
  catch-up on connect. SSE on Flutter means a hand-rolled streaming client and a
  server heartbeat to reach the same liveness.
- **Robust replay:** SSE `Last-Event-ID` would need a per-user event log on the
  server. ShipTrip's replay is the REST catch-up against the durable inbox
  (§15.5), which is transport-independent, so SSE adds nothing.

Chat stays WebSocket, as the plan says. **Future option, only if K6 T3 fires:**
carry chat and notifications on one socket. That halves sockets and reconnect
handshakes per user (~0.4 MiB to ~0.25 MiB).

## 15.2 Presence heartbeat

From the code: `presence.Refresh` does one SETEX at upgrade, then one every
`presenceRefreshInterval` = 5 s (TTL 15 s), plus one DEL at disconnect. Only
`/ws/notifications` does this, once per device.

| Online app users | Presence writes/s | Share of Redis |
| ---: | ---: | --- |
| 1 | 0.2 | — |
| 100 | 20 | — |
| 750 | 150 | about 3x the whole K6 estimate (50-60 ops/s), which omitted presence |
| 1,000 | 200 | |
| 10,000 | 2,000 | still about 2 orders of magnitude below one small Redis node |

The steady cost excludes reconnect bursts, which add 1 SETEX + 1 DEL per socket
cycle. Delivery receipts cost 1 SETEX (plus 1 Postgres UPDATE) per delivered
event per recipient.

**Verdict:** not material, so no change in K7. **Finding:** nothing reads
`presence:<uid>`. The FCM consumer suppresses on the per-event `delivered:`
receipt, and neither Django nor the mobile app reads presence. Every presence
write is pure cost. Later cleanup, owner's call: delete the loop, or lengthen it
to 20 s with a 45 s TTL. Two minor quirks go with it:

- `Drop` on one device's disconnect deletes the key while another device is
  still connected, for up to 5 s.
- The `PresenceTTL` comment has its ping-versus-TTL relationship backwards.

## 15.3 Buffers and backpressure

| Stage | Size | On overflow | Visible as |
| --- | --- | --- | --- |
| go-redis PubSub channel → `redisbus` pump | 100 → 1024 | drop | `pubsub_drops_total`, `pubsub_drops_<channel>`, warn with `event_id` |
| Dispatcher pool (notification) | 128 goroutines | **K7-E:** wait up to 250 ms for a slot (the pump buffer absorbs the burst), then drop | `dispatch_drops_total`, warn with `event_id` |
| Receipt pool | 64 goroutines | drop the receipt (the frame was already sent) | `receipt_drops_total`; effect: possible duplicate push and an undelivered audit row |
| Per-socket send buffer | 64 frames; 10 s write timeout; 10 s server ping | **now:** drop and disconnect, no receipt (defect 1) | warn log |

The metrics reach logs through the per-minute `ws_stats` line.

**Measured** (2,000 sockets, miniredis, loopback Postgres with pool 5):

| Load | Events | Delivered | Dispatch drops | Receipt drops |
| --- | --- | --- | --- | --- |
| Unpaced burst (~22 k events/s published) | 5,000, 2 targets each | 9,908 / 10,000 frames (99.1 %) | 46 | 6,732 |
| Chat relay, same burst | 5,000 | 9,946 / 10,000 | 27 | 7,030 |
| Paced 1,000 events/s | 5,000 | 10,000 / 10,000 | 0 | 0 |
| Paced 3,000 events/s | 9,000 | 18,000 / 18,000 | 0 | 0 |

**Tuning note, applied in K7-E (notification relay only):** `scheduleDispatch`
used to drop as soon as the 128 slots were busy, so the 1,024-slot pump buffer
never filled. It now takes a free slot at once when there is one, and otherwise
waits up to `dispatchSubmitTimeout` (250 ms, or until shutdown). While it waits,
the pump keeps buffering, so a burst is absorbed. Only a pool still full after
250 ms is treated as stuck: it drops and counts `dispatch_drops_total`, and
sustained overflow beyond that surfaces as `pubsub_drops_total`. A cancelled ctx
returns at once and is not counted as a drop. Unit evidence
(`TestScheduleDispatch_AbsorbsABurstWithoutDropping`, 2,000 events against a
2 ms-per-send hub): 1,278 dropped with the old non-blocking submit, 0 now. The
chat relay has the same non-blocking submit (27 drops in the burst above). It is
unchanged and is a one-line follow-up if wanted.

**Durability (no important event is realtime-only):** every targeted
`publish_after_commit` writes a `Notification` inbox row per recipient in the
business transaction. It also schedules a `notification_dispatch` job that
retries PUBLISH and the FCM enqueue if Redis fails. Chat messages persist in
`chat_message` before the publish. Offers, deal state, payment, handover,
payout, dispute and chat events all route this way. All 43
`publish_after_commit` call sites in production code pass `targets=`, which
was checked. **So a realtime drop only delays: the client re-reads on resume,
reconnect, navigation or push.**

**Gap (flagged, not fixed): Redis resubscribe window.** This was verified by
holding 200 sockets, killing miniredis for ~5 s, and restarting it:

- Both relays kept every socket.
- go-redis resubscribed silently.
- New events were delivered 100/100.

Events that Django *successfully* published while a relay's subscription was
down are lost from realtime, and connected clients get no trigger to catch up.
When Redis itself is down, Django's PUBLISH fails and the dispatch job retries
(30 s), so the realistic window is narrow: a relay-only disconnect from a
healthy Redis. Recovery waits for the next resume, navigation, other event or
push.

Possible fix for Codex: detect a resubscribe with go-redis
`ChannelWithSubscriptions` and close local sockets so clients catch up. That
fix causes a reconnect wave, so weigh it against §15.4.

## 15.4 Reconnect storms

**Client math (K5 `NotificationSocket`):** attempt *k* waits uniform
[2^k/2, 2^k] s, capped at [16, 32] s, and the attempt count resets only after
30 s of uptime. A server-side drop of a stable connection therefore retries in
**[0.5, 1.0] s**. That is 2 sockets per user, so 1,000 users means 2,000
connects in 0.5 s (~4,000/s).

**Server cost per connect:**

- HS256 verify, locally, with no DB.
- Notification: 1 Redis SETEX and 4 goroutines.
- Chat: no Redis, no DB, 3 goroutines.

**Measured** (`storm` probe: coder/websocket client on the same box as the
relays):

| Scenario | Result |
| --- | --- |
| Connect capacity, 150 concurrent dials | notification 6,900-8,500 connects/s (500-4,000 sockets, 0 failures, p99 ≤ 37 ms); chat 9,700/s |
| K5 first-retry wave, 1,000 users (2,000 sockets over 0.5-1.0 s) | 2,000/2,000, p99 dial 3 ms |
| 3,000 users (6,000 sockets over 0.5 s) | 4,191 ok, 1,809 refused by the **Windows 200-entry accept backlog** (Linux default 4,096); a platform artifact, and refused clients retry at 1-2 s |
| Hard kill of the relay, ~8 s down, 2,000 held sockets | while down, attempts ran 2,000 → 2,000 → 1,900 per backoff tier; after restart, **1,993/2,000 back in 6 s**, all in 14 s, peak 485 connects/s |

**10,000 users (extrapolated):** 20,000 sockets inside 0.5 s is ~40,000/s. That
exceeds one relay's ~8 k/s and a 4,096 backlog. Part of the wave spills into
the 1-2 s and 2-4 s tiers, which self-limits and settles in ~3-5 s. That scale
requires the realtime split anyway (K6 T3).

**The real storm cost is Django, not Go.** Every connect fires
`onConnected → reconcileScope`. `LiveUpdates` coalesces resume and both sockets
into one catch-up per 5 s, which re-reads unread-count plus every mounted
collection: deals, matches, requests/journeys, chat threads, the bell, and the
current route. That is about 5-7 GETs per user.

- **Current K6 shape** (~100-130 concurrent users, 33-50 RPS ceiling): a deploy
  produces ~700 requests in ~1 s, which saturates web for ~15-20 s.
- **1,000 users:** ~6,000 requests, about 2 minutes of backlog at today's
  ceiling.
- Today every web deploy also drops every socket, because it is one combined
  container.

Recommendations for the lead, not implemented:

- Split realtime (K6 T3/T5) so web deploys stop dropping sockets.
- Once online users pass ~300, spread the post-reconnect catch-up with random
  jitter (for example 0-5 s) when the drop was server-initiated.
- Cheapen `unread-count` (§15.6).

## 15.5 Missed-event recovery

**Client (verified in code):**

- **Resume from background:**
  `PushCoordinator.didChangeAppLifecycleState(resumed)` → `_reconcileCurrentScope()`
  plus a socket restart. Sockets are stopped on pause, so a backgrounded app
  always reconciles on return.
- **Each socket connect:** `onConnected` → `_reconcileCurrentScope()`.
- **Scope:** `LiveUpdates.reconcileScope` covers unread, the current route's
  resources, and every mounted collection. The route resources include the Deal
  detail (`deals/<id>`, plus payment), match and offers, and the chat thread.
- **Chat thread:** `ChatThreadController.reconcile` pages `after_id=<cursor>`
  until `has_more` is false, so no message gap survives a reconnect.
- **Events:** events are hints; every screen re-reads its HTTP endpoint, so a
  lost frame never leaves stale financial or lifecycle state patched locally.

**Server:** the server does no replay by design. The inbox (`Notification`),
`chat_message` and Deal endpoints are authoritative.

**Gaps:**

1. The Redis resubscribe window (§15.3): connected clients are not prompted.
2. Before this package, dropped slow-consumer frames were not prompted either;
   fixed (defect 1).
3. Before this package, the arrival events never arrived live; fixed (defect 2).
4. By design, detail screens held off-route in the `IndexedStack` are skipped by
   catch-up and re-read when opened. This is acceptable.

## 15.6 Chat scaling

**History cost.** Django with the real views and embedded Postgres, one
1,000-message thread, 15 repetitions:

| Request | Queries | Median ms |
| --- | ---: | ---: |
| `latest=1`, 50 rows (the thread open) | 5 | 9.5 |
| `after_id` delta, 5 new (the catch-up) | 5 | 6.2 |
| `after_id` delta, empty | 4 | 4.5 |
| `before_id`, mid-thread, 50 rows | 5 | 9.4 |
| Legacy `page=1` / `page=20` (offset 950) | 6 / 6 | 16.9 / 12.8 |
| `GET /api/chat/threads` | 5 | 13.3 |
| `POST` send (lock, insert, inbox row, dispatch job) | 16 | 10.4 |
| `GET /api/notifications/unread-count` | 3 | **38-42** |

- **History SQL:** the latest-50 query ran in 0.42 ms (bitmap scan on
  `match_id` and top-N sort, 20 buffers). Read cost is flat in thread length
  because every cursor read is `LIMIT page+1` on `(match_id, id)`.
- **Unread updates:** one `UPDATE … WHERE id IN (<returned ids>) AND read_at IS
  NULL` per read, plus a `Count` annotation in the thread list. Both are cheap.
- **Fan-out:** see §15.3. 6,000 frames/s paced with zero loss; ~42-45 k
  frames/s unpaced, with the pool drops noted there.
- **Sockets:** 0.4 MiB per app-open user (K6).

**Verdict:** no chat bottleneck, so nothing to optimise.

**Flag for Codex:** `unread-count` is the most expensive read in every catch-up
and bell refresh, and the cost is not data. Execution is 0.3 ms. About 14 ms
goes to ORM compilation of the `resolved_notifications` expression and ~8 ms
to Postgres planning, even for an empty inbox. It is worth addressing if K6 T1
(web CPU) fires, for example by precompiling or simplifying the resolution
annotation, or by using a partial index plus a simpler count.

## Method and reproduction

- **Relays:** built from this tree and run against miniredis
  (`backend/loadtest/tools/cmd/miniredis`) and an embedded pgserver Postgres,
  with a stub `core_published_event` table. Pools were `*_DB_MAX_CONNS=5` (the
  `start.py` values).
- **Probe:** `storm`, a throwaway Go client (not committed). Its modes:
  - `burst`: N concurrent dials.
  - `jitter`: dials at the K5 first-retry offsets.
  - `wave`: N clients running the exact K5 backoff while the relay was killed
    and restarted.
  - `fanout`: pipelined or paced PUBLISH with a `targets` envelope, counting
    frames read.
- **Django figures:** a temporary pytest probe on `test_pg` (not committed).
- **Honest limits:**
  - Windows loopback, and the client shares the CPU with the relays.
  - miniredis is not a Redis performance proxy.
  - Railway adds ~1 ms per Redis or Postgres round trip, which lowers the
    receipt rate, not fan-out.
  - The Caddy/TLS edge was not in the connect path; Railway terminates TLS at
    its edge.
