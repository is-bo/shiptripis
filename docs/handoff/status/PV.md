# PV status

Branch `claude/project-thread-hj6cnl`. Server only, no migration.

- Done: one re-encoder for parcel photos (both endpoints), ticket proofs and dispute photos; first
  names for anyone but the member and staff on journeys, proposals, chat, the blocked list and the
  recipient's email. "Own-card labels" closed with no case.
- Red commit `c36f864` (10 of 11 new tests fail), fix in the next commit.
- Payout evidence keeps its metadata, by decision with the lead (only audited Finance staff open it).
- Follow-ups: dispute videos keep their metadata; payout evidence could be re-encoded later; each
  upload is decoded twice (the type check, then the re-encode), which costs CPU but no correctness.
- Phase doc: `docs/PHASE_PV_IMAGE_METADATA_AND_NAMES.md`.
