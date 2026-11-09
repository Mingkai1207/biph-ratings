# Directory and reading-room exploration

Local design experiment, 3 November 2026. Do not push or deploy without a new user instruction.

## Intent

Make finding a teacher and reading existing student experiences the first actions.
The current homepage uses a large introductory panel and a grid of repeated cards;
the current profile puts the entire contribution form ahead of the comments.

## Proposed structure

- Directory: compact heading, persistent subject index on desktop, searchable teacher rows. Teacher and course lead; subject, rating, and review count use aligned columns. Mobile uses a subject select and a two-column row.
- Profile: teacher identity followed by a reading column and a compact rating sidebar. The writing form expands on demand. Existing reviews remain the primary content.
- Keep the BIPH blue and white palette, current fonts, English default and Chinese switch, anonymous reviews, ordinary search, rating controls, votes, sharing, and word-level blurring.
- No ranking section or AI search. No new promotional claims, stock imagery, or fabricated content.

## Isolation

Branch: `codex/directory-exploration`.

Worktree: `/Users/mingkai/Documents/ChatGPT/Websites/ratebiph-directory-study`.

The production checkout and deployment are unchanged. The preview uses an isolated SQLite snapshot under `/Users/mingkai/Documents/Codex/2026-11-03/ratebiph-structure`; local submissions cannot reach production. Search/filter and profile API calls remain same-origin.

## Files

- `frontend/index.html`, `directory-study.css`, `directory-study.js`: directory layout and controls.
- `frontend/teacher.html`, `profile-study.css`: reading-focused profile.
- `tests/directory_renderer.test.cjs`: user-content escaping, rating semantics, and bilingual labels.

Other routes retain the existing layout. This is an exploration of the two core browsing surfaces, not a production release.

## Hallmark refinement and campus background

The two core screens now use restrained typography, plain teacher rows, official BIPH overview/entrance photographs, and a fixed whole-page rooftop soccer-field background explicitly requested by the user. A continuous white gradient protects contrast; the initial solid reading sheet was removed at the user’s request. The two inset decorative photos are hidden in this treatment. Shared local system: `DESIGN.md`, `frontend/study-system/`, and `frontend/campus-header.css`. Photo provenance: `docs/biph-photo-sources.md`.

Full comparison and verification: `/Users/mingkai/Documents/Codex/2026-11-03/ratebiph-hallmark/RESULT.md`. New CSS static scan: 0 FAIL / 0 REFLEX / 0 WARN. CUA desktop/mobile review: ship. Existing renderer tests: 7 passed; preceding Python suite: 116 passed. No deployment.

Latest user correction: photos now appear only in the page headings. The full-page photograph and gradient have been removed. Desktop uses side-by-side heading/photo layouts; mobile stacks compact112px images. Plain white search and review areas. Verified desktop/mobile; local only.

Current heading treatment: full-width campus image behind the heading, white-to-transparent horizontal fade from left to right. Plain white content below. Desktop240px / mobile200px minimum height; photo and overlay ignore pointer events.

Latest roster refinement: plain name/subject/course entries with quiet rating/review summaries; only the unfiltered list has letter groups. No table column headings or per-row dividers. Subject labels and search are simpler. Approved header retained.10Node tests and CUA search/filter/language/narrow-screen checks passed; local only.
