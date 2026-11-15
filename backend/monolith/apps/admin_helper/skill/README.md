# Wassla admin helper skill

The skill an admin's own AI assistant uses to do Wassla admin work and to answer questions about the
app. Product rules: `docs/WASSLA_DISCOVERY_PRO_SPEC.md` section 20. Build: plan packages L15, L16, L17;
phase doc `docs/PHASE_L17_ADMIN_HELPER_SKILL.md`.

## Files

- `SKILL.md`: the skill (`name: wassla`, at most 140 lines): the protocol and a routing table.
- `knowledge/*.md`: the notes, one topic per file, written from the code. Edit these when the app
  changes; every claim should be true to the code.
- `INSTRUCTIONS.txt`: **generated**, never edited by hand. `manage.py build_helper_instructions`
  rewrites it from `SKILL.md` and `knowledge/`; a test fails when it is stale.

The console serves them: the AI helper card's "Download the skill" (a zip of the folder `wassla/`) and
"Copy the instructions" (`INSTRUCTIONS.txt`'s text). Neither holds a key or an address; the line the
console copies supplies both.

## Rules for editing

- Facts come from the code, not from docs. Say "the notes do not say" rather than guess.
- No `UNSURE:` left in a notes file (a test fails). Each notes file starts with a title, a `Covers:`
  line and a `Related files:` line naming only existing notes files.
- Keep `SKILL.md` at 140 lines or fewer; put knowledge in `knowledge/`.
