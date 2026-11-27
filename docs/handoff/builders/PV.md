# Brief PV: stored photos without metadata, and names in payloads

**Builder:** Claude Opus, high effort.
**Branch:** new, from the tip of `main`. Server only. L2 starts after you merge.
**Starts:** when the lead gives you Ismail's answers to the plan's decisions.
**Read first:** `CLAUDE.md`, the product invariants above all; `docs/handoff/builders/README.md`;
the plan (`docs/handoff/LOOP_END_PLAN.md`) sections 3 and 6; `docs/PHASE_P3A_PROFILE_PHOTOS.md`
for how profile photos are already cleaned; `backend/monolith/apps/core/storage.py`.

## 1. Your job

Three older privacy findings from `HANDOFF.md` 0.7.

1. **Photos keep their metadata.** A parcel photo is stored exactly as uploaded
   (`apps/parcels/views.py`, `_store_image`), so it keeps the GPS position of the place where it
   was taken, often the sender's home. A traveler who can open the photo can read it. The rule
   "exact locations stay hidden until the deal is funded" is broken by the file itself.
2. **The traveler's full name** is in the journey payload (`apps/trips/serializers.py`,
   `traveler_name`), while listings use the first name (`first_name()` in
   `apps/matching/find_travelers.py`).
3. **"Own-card labels."** No description exists in the repository.

## 2. What you build

Paths are under `backend/monolith/`.

**One function writes every stored image again from its pixels** (`apps/core/storage.py`).
`square_jpeg_without_metadata` already does this for profile photos: upright, flattened, a new
JPEG with no EXIF, XMP, ICC profile or comment. Give the same code a path that keeps the image's
shape and limits its longer side, and use it for:

- parcel item photos (`apps/parcels/views.py`, both callers of `_store_image`);
- dispute evidence (`apps/disputes/services.py`, the upload near line 953);
- flight and sea proofs (`apps/trips/views.py`, the upload near line 550).

The limits on input size and pixels that the callers have today stay. A file the decoder refuses
is rejected with the code the caller already uses. Choose a longer-side limit that keeps a ticket
readable, and say which. Payout evidence (`apps/finance/payout_evidence.py`) is said to be
cleaned already: confirm it with a test and change nothing there.

**Names.** List every payload field that carries a member's name, with who can receive it. Follow
the specification's rule for names (`docs/SHIPTRIP_V1_SPEC.md` and the addendum). Where it is
silent: anyone but the member and staff gets the first name only, and you tell the lead which
fields that changed. Each changed payload gets a privacy test.

**Own-card labels.** Ask the lead what Ismail saw. With a concrete case, fix it here if it is a
server payload, or hand it to the lead as an app item. With no case, write in the pull request
that it is closed.

## 3. What is not yours

Profile photos (already clean). The app. Any change to who may open a photo.

## 4. Tests

Red first: upload a parcel photo that carries a GPS position, download the stored object, and
find the position in it.

- For each of the three upload paths: an image with EXIF GPS, XMP and a comment is stored
  without them; all eight orientations come out upright; a transparent PNG is flattened; a
  corrupt file, an animated file and a decompression bomb are refused; the stored object is a
  JPEG and its recorded content type says so.
- Payout evidence carries no metadata.
- Each name field: what the owner, the other party before funding, the other party after
  funding, a guest and staff receive.

## 5. Done when

1. The red test is green, and every case of section 4 passes.
2. The pull request lists the name fields with their audience and what changed.
3. The phase document and the status entry are written.
4. Every CI check is green.
