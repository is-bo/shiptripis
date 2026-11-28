# Phase PV: stored photos without metadata, and names by audience

Package PV of the loop-end plan (`docs/handoff/LOOP_END_PLAN.md` section 6), brief
`docs/handoff/builders/PV.md`. Server only. No migration, no app change. Nothing deployed.

## 1. Photos are written again from their pixels

A parcel photo, a ticket proof and a dispute photo were stored exactly as uploaded, so a photo
taken at the sender's home carried its GPS position to anyone allowed to open it. That broke
"exact locations stay hidden until the deal is funded" through the file itself.

`apps/core/storage.py` now has one private re-encoder, `_jpeg_from_pixels`, used by two shapes:

| Function | Shape | Animated file | Used by |
|---|---|---|---|
| `square_jpeg_without_metadata(body, size=)` | centred square | first frame (unchanged) | profile photos (P3A) |
| `jpeg_without_metadata(body, max_side=2560)` | kept; longer side at most 2560 px, never enlarged | refused | parcel item photo, parcel attachment, ticket proof, dispute photo |

Both decode under the existing pixel ceiling (`MAX_IMAGE_PIXELS`, and the WebP header check),
turn the image upright from its EXIF orientation, flatten transparency onto white and write a
new JPEG from pixels only: no EXIF, XMP, ICC profile or comment survives.

**2560 px** keeps a boarding pass's small print and barcode readable, and a phone photo of a
parcel at full detail, while capping the stored size.

Callers keep every check they had (size limit, declared type against the real bytes) and the
refusal code they already used, now also for a file the decoder refuses or an animated file:

| Path | Code |
|---|---|
| `POST /api/parcels/media`, `POST /api/parcels/<id>/media` (`_read_image_upload`) | `parcel_photo_media_type_unsupported` (415) |
| `POST /api/journeys/<id>/legs/<id>/proof` | `proof_media_type_unsupported` (415) |
| `POST /api/disputes/<id>/evidence`, kind photo | `dispute_evidence_content_mismatch` (409) |

The stored object is always `*.jpg` with content type `image/jpeg`, and the row records
`image/jpeg` and the stored byte count (and, for dispute evidence, the stored file's SHA-256).
`_store_image` lost its `ext` and `content_type` parameters, which can no longer differ.

**Not changed:**
- **Dispute videos** are stored as sent; an MP4 or MOV can carry a position too. Outside the brief
  (follow-up).
- **Payout evidence** (`apps/finance/payout_evidence.py`) is *not* cleaned, contrary to the
  brief's note: the cheque photo is encrypted and stored as uploaded. Decided with the lead: no
  change here. It is not a leak, because only the owner uploads it and only Finance staff holding
  both `view_payout_sensitive` and `view_payout_evidence` can open it, each open audited.
  Re-encoding it is on the follow-up list as a later option.
- Profile photos and KYC documents.

## 2. Member names by audience

The specification forbids a last name on any public surface (addendum 4.2). Where it is silent,
the brief's rule holds: the member and staff get the whole name, everyone else the first name.
`first_name()` stays in `apps/matching/find_travelers.py`; `name_seen_by(viewer, member)` sits
beside it for the two payloads that a member and staff may both read.

| Field | Endpoint | Owner | Other party (before and after funding) | Guest | Staff | Changed |
|---|---|---|---|---|---|---|
| `traveler_name` | journey detail and list (`JourneySerializer`) | whole | first | 401 | whole | **yes**, was whole for all |
| `sender_name`, `traveler_name` | proposal detail and list (`MatchSerializer`) | whole (own) | first | 401 | 403 (console only) | **yes**, was whole for both |
| `counterparty_name` | `GET /api/chat/threads` | n/a | first | 401 | n/a | **yes**, was whole |
| `name` | `GET /api/me/blocks` | n/a | first (the blocked member) | 401 | n/a | **yes**, was whole |
| `sender_name` | recipient's delivery-code email | n/a | first (the recipient is a guest) | first | n/a | **yes**, was whole |
| `display_name` | discovery cards, profiles, alerts, Find Travelers | first | first | first | first | no, already first |
| `full_name` | `GET/PATCH /api/me` | whole | n/a | n/a | n/a | no, own account |
| `traveler_name` and the console pages | admin API and console | n/a | n/a | n/a | whole | no, staff |
| recipient `full_name` | deal recipient block | sender (whole), traveler after pickup | | | whole | no: typed by the sender for the handover, not a member's name |

## 3. "Own-card labels"

`HANDOFF.md` 0.7 names it without a description, and nobody could give a concrete case.
Closed with no change, as the brief says.

## 4. Evidence

| Rule | Red (fails at `c36f864`) | Green |
|---|---|---|
| A GPS photo is stored without GPS, camera, XMP or comment, as a JPEG, shape kept, recorded as `image/jpeg` | `test_stored_images_without_metadata.py::test_a_photo_with_a_gps_position_is_stored_without_it` | same, after the fix |
| All eight orientations come out upright | `::test_all_eight_orientations_come_out_upright` | same |
| A transparent PNG is flattened onto white | `::test_a_transparent_png_is_flattened_onto_white` | same |
| The longer side is brought down to 2560 px | `::test_the_longer_side_is_brought_down_to_the_limit` | same |
| A corrupt, an animated and a bomb file are refused with the caller's code | `::test_a_corrupt_an_animated_and_a_bomb_file_are_refused` | same |
| Names, each field and audience of section 2 | `test_member_names_by_audience.py` (6 tests, 5 red) | same |

Each image test runs its whole table on all four upload endpoints through HTTP, and reads back
the bytes handed to the object store. The profile-photo tests (`test_p3a_image_reencode.py`)
cover the square shape unchanged.
