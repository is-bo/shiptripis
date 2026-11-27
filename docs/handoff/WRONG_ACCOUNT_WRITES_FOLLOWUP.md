# Follow-up package: wrong-account writes outside the profile photo

Status: **not started.** Written 2026-11-27 from Astra's P3B round-7 review
(`docs/handoff/astra/results/p3b-astra-round7-result.md`). Ismail's triage (round 8 of P3B): these
flows are outside the photo package, so P3B does not fix them. They are recorded here as one package
for the coordinator to plan and assign.

Not a legacy or upgrade concern: the app has never been live, and none of this is about old data.

## The problem

A member's write is built from state that was drawn or filled in while member A was signed in, and
is sent when member B is (a direct sign-in over A, with no sign-out in between). The write then goes
out under B's bearer. The server accepts it as B's. The photo package closed this for photo writes
with `MemberScope` (see below). These screens still read "who am I" at send time.

## The sites Astra found

| Flow | Where | What goes wrong |
|---|---|---|
| Public profile (Home opt-in, route editor) | `mobile/lib/app/discovery_state.dart:277` (`_apply`), `mobile/lib/features/discovery/public_profile_screen.dart:64` (`_addRoute`) | The writer checks only `photoWrites`. A's Home opt-in can record public-profile consent for B. The route editor keeps A's route list across two city pickers and can `PUT` it to B's `/api/discovery/profile/me`. |
| KYC (ID and selfie) | `mobile/lib/features/kyc/kyc_screen.dart:145`, the KYC upload near `:2257` | The shared picker returns a bare `XFile`. A's selected ID and selfie stay in the form across an account change. Submitting reads the current bearer after the files are opened, so A's documents can be filed as B's KYC. |
| Payout cheque form | the cheque upload near `:162` | Same: A's file and bank fields stay in the form, and the proof upload can start under B. |
| Account deletion | `mobile/lib/features/profile/delete_account_screen.dart:69` | A opens the dialog, B signs in, confirmation posts `/api/me/deletion` with B's bearer. For an eligible B (Google only, no password, no Apple identity, no blocker) the server deletes B. |
| Sign-out dialog | `mobile/lib/features/profile/profile_screen.dart:225` | Acts on whoever is signed in at confirmation. |

The photo package covers its own writes only. Line numbers are Astra's at `a286b34`; re-find them.

## Is the fix cheap now? Mostly yes, in two sizes

`MemberScope` (`mobile/lib/core/session/member_scope.dart`) is the primitive. A screen takes one with
`SessionController.beginAction()` when the member first touches the flow, carries it through every
sheet, dialog and file picker, and the commit asks `isCurrent(scope)` once. The server-facing half
exists too: `ApiClient.upload` and `deleteVoid` take `expectedIdentity` and `expectedAccount`, and
the auth interceptor refuses a bearer that belongs to another account (`bearer_account.dart`).

* **Cheap (one small change each, the primitive is enough):** account deletion, sign-out, and the
  public-profile writer. Capture the scope before the dialog or first picker, pass it to the write,
  re-check `isCurrent` before applying the answer. For deletion also clear local credentials only
  if the same session still owns them (`accountDeleted()` already takes the identity it clears).
* **Not as cheap:** KYC and cheque. They need `postObject`, `putObject` and multipart sends to
  accept `expectedIdentity` and `expectedAccount` the way `upload` does, and each private form has
  to own its scope and its selected files, clearing both when the member changes. Medium size, and
  it touches identity documents, so it belongs to the strongest model.

## Suggested shape

1. `ApiClient`: one optional scope on every write method (`postObject`, `postVoid`, `putObject`,
   `patchObject`, multipart), not only `upload` and `deleteVoid`. The refusal path already exists.
2. Each flow takes a scope at its first touch and sends with it. A write whose scope is stale
   returns an explicit stale result, as `ProfilePhotoRemoval.stale` and the profile updates do.
3. KYC and cheque forms clear their fields and selected files when `accountSession` changes.
4. Tests per flow: A's control or dialog, B published, a press or confirmation before the next
   frame, no request sent. Mutation-check each.

## Plan inputs

* Model: strongest (Opus) at high or extra-high effort. It touches identity documents, account
  deletion and payout documents.
* Independent gate pass by Astra on races and authorization.
* Scope: nothing outside these five flows; no new endpoints.
