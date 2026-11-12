# Wassla admin helper skill

Instructions that let an admin's own AI assistant guide them through their Wassla admin work.
Product rules: `docs/WASSLA_DISCOVERY_PRO_SPEC.md` section 20. Build: plan packages L15, L16, L17.

**It works only once L15 and L16 are built.** It was drafted on 2026-11-12, before the helper
exists, against the contract in the plan. Package L17 checks it against the real helper and proves it
with a small model.

## Files

- `SKILL.md`: the skill, named `wassla`, so the admin starts it by typing `/wassla`.
- `INSTRUCTIONS.txt`: the same text without the skill header, for assistants that take pasted
  instructions.

## How an admin uses it

1. Install once. In Claude Code: put `SKILL.md` in `~/.claude/skills/wassla/`. In another assistant:
   add `INSTRUCTIONS.txt` as a rule or command named `wassla`.
2. In the Wassla admin console, on the home page, card "AI helper": "Create read key", then "Copy".
   The copied line is `/wassla <address> <key>`.
3. Paste it into the assistant.
   - Nothing after it: the assistant gives the briefing.
   - A question after it ("how do I refund someone?", "what is WSL-7K3M9QXD waiting for?"): it
     answers that.
4. For the rest of the conversation, just ask. No need to paste the key again until it expires
   (8 hours).

Neither file contains a key or a server address. Both arrive in the line the console copies.
