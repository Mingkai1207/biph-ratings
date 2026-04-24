# CLAUDE.md — Working Habits for This Repo

Instructions for Claude Code when working on `biph-ratings`.

## Scope discipline — only edit what the user asked for

**The habit:** only edit the things the user explicitly asked you to change. Don't touch code, styles, or behavior that weren't part of the ask.

**Why it matters:**
- The user can review a small diff. They cannot review a sprawling one.
- Unrequested "improvements" hide real bugs in the noise of cosmetic changes.
- Trust compounds. Every unrequested edit is a paper cut on trust. Every clean, scoped diff is a deposit.
- When something looks wrong nearby, the user has context you don't — maybe they know about it, maybe it's intentional, maybe they're planning to fix it in a different PR.

**What this looks like in practice:**
- If the user says "add a star trail cursor," change the code needed for a star trail cursor. Don't also refactor `app.js`, don't rename variables, don't "tidy up" adjacent CSS.
- If you notice something genuinely broken outside the ask, **flag it in chat, don't fix it silently.** One sentence: "By the way, I noticed X — want me to fix that too or leave it?"
- If a fix requires touching a second file, say so before touching it. Example: "To add the aura, I need to set a CSS variable on each card in `index.html`'s render loop — OK to edit there too?" (For tight, obvious dependencies like this, doing it is usually fine — just name it in the commit message so the user sees the scope.)
- Commit messages should match the ask. If the user asked for A, the commit shouldn't secretly include B, C, and D.

**The test before any edit:**
> "Did the user ask for this specific change, or am I adding it because I think it'd be nice?"

If the answer is the second one, stop. Ask first, or cut it.

**Exceptions — when going slightly wider is the right call:**
- A fix the user asked for can't land without a small adjacent change (e.g., adding an import, wiring a prop through, updating a type). Do it, but name it in the PR/commit body.
- The user's change introduces a bug they'd immediately hit (e.g., a typo in the string they gave you). Fix it inline, mention you fixed it.
- A lint/format rule would block the commit on a line you already touched. Format that line.

Everything else: flag it, don't ship it.

## Voice

Direct. Concrete. Name the file and line. No throat-clearing. Match the gstack/GStack voice already established in this session — builder-to-builder, not consultant-to-client.

## Testing

Run: `./venv/bin/python -m pytest` from the repo root. Tests live in `tests/`. See `TESTING.md` for the full guide.

Expectations:
- 100% coverage is the goal. Tests make vibe coding safe.
- New function → corresponding test.
- Bug fix → regression test that would have caught it.
- New error handler → test that triggers the error.
- New conditional (if/else, switch) → tests for BOTH paths.
- Never commit code that makes existing tests fail.
