# L4: the other compatibility code

Brief `docs/handoff/builders/L4.md`, plan section 7.1, decision D4. Code that existed only so an
older client, key or row kept working goes; anything with a live reader or writer stays. No
migration, no switch, no app change. Nothing deployed. Behaviour of the app and console is unchanged.

## Inventory

| Item | Verdict | Evidence |
|---|---|---|
| `LEGACY_ADMIN_GROUP_TO_ROLE` and the Phase 4 group removal in `assign_admin_roles` (`apps/admin_panel/permissions.py`) | **Removed** | Migration `admin_panel.0002_seed_roles` (depends on `core.0007`, which created the four groups) moves every member to the current role and deletes the groups. Nothing creates them again: invitation acceptance, `change_admin_role` and `bootstrap_super_admin` all go through `assign_admin_roles`; the Django admin shows groups read only (D5). |
| `core/historical_admin.py` (plan 7.1) | Already removed | L1 (#74) deleted it. |
| `paginated_array_response` for `/api/journeys`, `/api/parcels`, `/api/locations`, `/api/payments/orders`, `/api/matches` | **Kept, because the app reads the array** | `mobile/lib/data/repositories.dart` reads them through `ApiClient.getList` / `getAllPages`, and `getListPage` reads `X-Next-Page` and `X-Total-Count` on an array body (`mobile/lib/core/api/api_client.dart`). The module docstring now says it is the current contract. |
| The disputes app's own `GET /api/admin/disputes` (`apps/disputes/views.AdminDisputeListView`, bare array) | **Removed** | Never reached: `config/urls.py` includes `apps.admin_panel.urls` first, and its view answers the same path with the paginated envelope. Its only permission class, `core.permissions.CanViewDisputes`, went with it. |
| Chat history page-number form (`ChatMessagesView.list`) | **Removed** | The app reads only `latest`, `after_id`, `before_id` (`mobile/lib/features/chat/chat_thread_controller.dart` lines 156, 234, 300; `repositories.dart` never passes `page`). A read without a cursor now answers the latest window. The response keeps `"next": null`, which `ChatMessagePage.fromJson` reads. `_Pagination` stays: the thread list uses it. |
| `legacy_key` (`delivered:<event_id>`) in `sweep_published_events` | **Removed** | Every writer writes `delivered:<event_id>:<user_id>`: `internal/notification/dispatcher.go:410`, `internal/chat/dispatcher.go:355`; FCM reads the same form (`fcm.go:439`). Nobody writes the bare key. |
| "Legacy keys" branch in `internal/notification/dispatcher.go` (empty `targets`) | **Kept, because it is live**; comment corrected | `redis_bus.publish_after_commit` without `targets` publishes `"targets": []` on purpose (many callers). The branch is that case. |
| "Orphan legacy stream" in `internal/email/receipts.go` (`pgx.ErrNoRows`) | **Kept, because it is the guard**; comment corrected | A stream entry with no obligation row must be acknowledged and never sent; without the branch it would fall to "obligation unavailable" and stay in the pending list for ever. |
| "Still TODO" mTLS comments in `cmd/kyc/main.go`, `internal/kyc/grpc_client.go`, `pkg/config/config.go` | **Corrected** | Django's `runkycgrpc.py` serves the mTLS branch, and `scripts/gen-mtls-certs.sh` makes the certificates. The "Deferred: GET /kyc/me" note goes: KYC status comes from the profile's `kyc_status`. |

Lines: 103 removed and 24 added outside tests; 166 removed and 142 added in all (the new grant test
is 98 lines).

## Tests

| Test | What it covers |
|---|---|
| `apps/admin_panel/tests/test_admin_role_grants.py` (new) | For each grant path (invitation for a new account, for an existing account, role change, Super Admin bootstrap): exactly the role's group and exactly the role's capabilities; no Phase 4 group exists after migrations. Committed first (`64123f0`) and green on unchanged code, then green after the removal (`dd77485`). |
| `test_phase6a_admin.py::test_roles_are_fixed_and_privileges_are_revoked_on_downgrade` | Rewritten: it added a Phase 4 group as a fixture, which no path can create now. It still checks a downgrade revokes the old role. |
| `test_phase_k7d_admin_dispute_list_pagination.py` | Two tests that called the shadowed disputes view directly are removed with the view. The test of the served endpoint stays. |
| `test_disputes.py::test_the_admin_queue_requires_the_named_permission` | Reverses the served route name `admin-dispute-list`; same URL. |
| `test_live_history.py::test_a_read_without_a_cursor_is_the_latest_window` (new) | No cursor answers the same window as `latest=1`. The `{"latest": "1", "page": "2"}` refusal row is removed with the page form. |
| `test_redis_bus.py` sweep tests | Assert the per-user receipt scan instead of the bare-key `EXISTS`. |

## Seen outside the brief (for DC)

- `apps/disputes/views.AdminDisputeStatusView`, `AdminDisputeResolveView` and `AdminDealNoShowView`
  are shadowed the same way by the admin panel's routes, and the rest of `apps/core/permissions.py`
  (and its docstring about the four seeded groups) serves only them and `CanSettlePayouts`.
- The app's `ChatRepository.messages(page:)` parameter and `ChatMessagePage.next` exist only for the
  removed page form (MC).
- The notification dispatcher logs every untargeted publish at warning level.
