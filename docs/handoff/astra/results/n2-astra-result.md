I found no reachable defect in PR #70’s three-dot diff from `origin/main` to `0ff0b17de3b947d83812526b3e773f0c3e947fb6`.

| Severity | File and line | Concrete failure | Suggested fix |
|---|---|---|---|
| — | — | None found | — |

- **Contract and navigation.** The staff publisher supplies `mode`, `outcome`, `status`, and `journey_id`, and the inbox API preserves them. For both `FLIGHT` and `SEA`, all three decisions select the intended title. In particular, `outcome: resubmission_requested` takes precedence over `status: rejected`. An absent outcome uses the stored status. A drive, an unknown mode or decision, or missing decision data keeps “Verification update.” KYC keeps its existing label, and tapping a ticket opens the journey identified by `journey_id`. The diff contains no server change.
- **Privacy and copy.** The visible title and screen-reader label use the same localized string. Neither includes the staff reason, evidence, document ID, or proof ID. All 18 titles agree with the push matrix in wording, with typographic apostrophes in French. The Arabic is Modern Standard Arabic. None of the new titles contains a brand name.
- **Layout and tests.** The 360 px English and Arabic screenshots show readable rows and correctly mirrored RTL layout. The title can wrap across lines, and the row can grow vertically. The new tests assert all six English titles at 320 px, status fallback, generic labels, privacy of visible text, journey navigation, and French and Arabic approval copy. No existing test was changed or weakened.

I inspected the tests without running Flutter in this read-only review. The screenshots and tests do not demonstrate the longest French or Arabic titles at enlarged text sizes. I verified the screen-reader label in code only.

Overall verdict: approve