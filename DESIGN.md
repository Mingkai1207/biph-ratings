# Design: Rate BIPH

The directory and teacher profile design was deployed on 9 November 2026.
The same system extends to the About and contribution pages.

## System

- Scope: app screens, a searchable directory and a reading-focused profile.
- Theme: existing BIPH blue and white brand, school-roster typography.
- Structure: simple subject index and alphabetical teacher roster; rating sidebar and review column.
- Material: actual school campus photographs, actual teacher names and reviews.
- Posture: restrained. Blue marks linked names, actions and selected controls; supporting data uses quiet ink.

## Tokens

`frontend/study-system/tokens.css` is the source of truth for the study.
Existing brand values come from `frontend/styles.css`, not a new palette.

- Paper: `var(--bg)` / #ffffff.
- Ink: `var(--ink)` / #333333.
- Muted: `var(--ink-mute)` / #606975.
- Accent: `var(--accent)` / #3255a4.
- Line: `var(--line)` / #dce1e9.
- Functional headings, names, figures and body: Geist / `var(--font-sans)`.
- Wordmark: the existing Instrument Serif / `var(--font-serif)`.
- Type: 12,14,16,20,24,32,40px; 48px overall score.
- Spacing: 2,4,8,12,16,24,32,40,48,64,96px.
- Container:1120px on a plain white page; desktop inner gutters40px, phone inner gutters24px (16px at narrowest breakpoint).
- Corners:2px controls, square photo frames; no card shadows.

## Directory roster

- Plain linked teacher names, with subject and non-duplicate course context underneath.
- One quiet rating/review summary; exact ratings retain two decimals and review counts always include localized words.
- No card containers, column labels or per-row dividers. A single fine rule separates letter groups.
- Letter groups appear only for the unfiltered roster, preserving API ordering and handling Unicode initials. Search/filter results remain a simple list.
- Subjects use ordinary text controls without a numeric count column. Long labels wrap.
- Search uses a conventional text field with a light bottom rule and a quiet44px-high action.
- Existing API, live result status, error/retry behavior, focus states, row links and escaping remain.

## Controls and content

- Keep established API, language, filter, rating, sharing and vote handlers.
- Instant visible focus. Native form disclosure and mobile subject select.
- English by default; Chinese switch also translates new photo captions/alt text.
- Sensitive words continue through `RB.renderComment` unchanged.
- No ranking section, AI search, invented counts, or fake portraits.

## Photography

- Latest user direction: photographs fill the heading, with a horizontal white fade strongest at the left and clear image color at the right. No full-page background.
- Directory header: campus aerial view behind the title. Teacher header: school entrance behind the teacher identity. The text stays on the light left side.
- Desktop heading minimum height240px; mobile200px, expanding for longer text. Photo and gradient span the entire heading, including container gutters.
- Plain white reading area. Header-only white gradient is explicitly user requested. Overlay and image layers ignore pointer events; heading controls remain above them. No animation.
- Originals from the official BIPH website, provenance in `docs/biph-photo-sources.md`.
- Descriptive bilingual alt text, fixed dimensions, source credit near the footer.
- No claims of school endorsement; independent-site disclosure remains.

### Integrated photographic mastheads

- The user rejected isolated side pictures and a large photo appended below the About text. Photographs now define the opening of each supporting page instead of occupying spare space.
- About uses the field; Add a teacher uses the entrance; Suggestions uses the auditorium. One purposeful photograph per supporting page.
- Each masthead is a continuous image with a left-white/right-clear fade. Heading and introduction align to the same40px gutter as the text and form below.
- A plain white content surface starts32px inside the masthead's lower edge. It is left-aligned, at most800px wide, with no border, shadow or rounded outer form card. The overlap becomes16px on mobile with24px gutters (16px at320px).
- The mobile masthead grows with its text, protecting the introduction from the following content. Text uses dark ink; the stronger mobile fade protects contrast.
- Keep desktop captions small, on white space beneath the image's exposed right edge. On mobile, translated image alt text identifies the photograph without an extra caption row.
- The directory's isolated library thumbnail and duplicate About auditorium are removed. The campus link remains, and the accepted directory/profile headings are unchanged.
- All image dimensions are reserved; masthead images use high fetch priority. Original official image files are retained without editing.
- Shared layout: `frontend/campus-life.css`; source metadata stays in `docs/biph-photo-sources.md`.

## Exports

`frontend/study-system/tokens.css` and `base.css`; page-specific styles consume them.

Header treatment: `frontend/campus-header.css`; the superseded background stylesheet was replaced.
