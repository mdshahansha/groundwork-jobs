# Approved fixed-template PDF backend

Decision date: 2026-10-29. The product owner approved fixed templates instead of
Docker or executable custom LaTeX templates. This supersedes the initial LaTeX
selection for the first usable slice, not the requirement for factual/privacy gates.

## Contract and threat boundary

`jw draft-render` accepts `{task_id, output_path}`. It reads a completed CV or
letter task, rechecks current profile/evidence dependencies and assertion support,
then creates a new private PDF. Existing output files are never overwritten.
The destination parent must exist and the filename must end in `.pdf`.

The pinned optional renderer is ReportLab 4.4.9. `render_private_pdf` accepts only
closed-schema text fields. It uses `Canvas.drawString`, not ReportLab's markup,
XML, image, URL, arbitrary-font or custom-template interfaces. LaTeX commands,
HTML and path-looking strings remain literal glyphs. There is no process launch,
network request, shell escape, template command or Docker dependency.

This is **data-only rendering, not an OS sandbox**. It does not claim protection
from a compromised installed dependency or a hostile process running as the same
user. ReportLab reads its trusted packaged resources. No untrusted image, font or
PDF input is parsed by this backend. Custom LaTeX templates remain unsupported.

## Layout and limits

Fixed A4 portrait, 48-point margins, Helvetica, 11-point body, 16-point minimum
leading, one page. CV and letter have fixed titles and private-draft warnings.
The renderer wraps by measured glyph width, including unbroken tokens. It neither
shrinks fonts nor drops content. An overfull page raises `page_fit_conflict` before
creating output. The caller must select less draft content; automatic omission
of protected employment records is not implemented or authorized.

At most 100 assertions, 2000 characters each and 20000 total assertion characters.
The initial font contract is Windows-1252/Latin text, with newline/tab handling.
Unsupported characters raise `unsupported_glyph`, not silent replacement. This
does not satisfy unrestricted multilingual document support. Output is invariant
for identical supported inputs and the pinned renderer.

Results report `ready=false`, private-review classification, template version,
renderer version, SHA-256 and page count. Claim maps and raw source pages are not
embedded. Successful rendering does not pass the six document gates. PDF export
is an external local copy; later source deletion cannot recall that copy.

## Reproducible qualification

Install `.[render-test]`, set `PYTHONPATH=src`, then run:

```text
python -m unittest discover -s tests -p test_jw_rendering.py
python tools/probe_fixed_renderer.py --output-dir testing/render-probe-NEW
pdftoppm -scale-to 1200 -png -singlefile testing/render-probe-NEW/draft_cv.pdf testing/render-probe-NEW/cv
pdftoppm -scale-to 1200 -png -singlefile testing/render-probe-NEW/draft_letter.pdf testing/render-probe-NEW/letter
```

Use a new destination for each probe; overwriting is intentionally rejected.
Observed 2026-10-29: Python 3.12, ReportLab 4.4.9, pypdf 6.10.0, Poppler 26.07.0
on Windows. Seven renderer tests and one workspace privacy test passed. CV and
letter each produced one page; both PNGs were visually inspected with no clipped,
overlapping or missing fixture text. Poppler warned about unused fallback fonts
`Symbol` and `ArialUnicode`; the Latin fixtures rendered legibly. That warning
does not establish support for other scripts.

Synthetic probe PDF hashes:

- CV: `4e308ff6e45106b0d5d796bb2b89310403ddfcb3edbc9be84236e5ce0ecffbc3`
- Letter: `343724fd8c6d78d5671f910a53802728aac922001a6586018675d60eff832b95`

Tests cover deterministic bytes, text extraction, literal hostile markup,
network/process tripwires, no active PDF actions/annotations, overflow, glyph
rejection, missing/wrong dependency, exclusive output, restricted-data exclusion
and stale/revoked-source rejection. These are bounded fixtures, not proof of the
complete JW-09 visual-quality or reviewer-evaluation acceptance criteria.

Reference: [ReportLab graphics/text API](https://docs.reportlab.com/reportlab/userguide/ch2_graphics/).

## Mechanical gates 1-2 (JW-09, private-fixed@2)

`private-fixed@2` adds one line to letters, `Application for <title> at
<company>`, from the pinned job snapshot. CVs are unchanged apart from the
template version, so the 2026-10-29 probe hashes above are for `@1` only.

`jw draft-verify` (`task_id`) renders the draft in memory, writes no file, runs
`mechanical-gates@1` on the bytes and stores the run in `verifications` (schema 7)
with the PDF SHA-256. `draft-render` runs the same gates and returns them as
`verification`. The checks read the PDF back with pypdf instead of trusting the
renderer's layout report. Glyph boxes use Helvetica AFM ascender/descender
metrics with ReportLab's width tables.

| Gate | Check | Fails when |
|---|---|---|
| 1 | compiles | unreadable PDF or page count other than one |
| 1 | transform | rotated, skewed or mirrored text |
| 1 | text_clipping | a glyph box leaves the page inset by 36 points |
| 1 | overlap | two text boxes intersect |
| 1 | font_consistency | a font other than Helvetica, or a size outside 9/10/11/13/18 |
| 1 | footer_collision | footer missing, duplicated, or above the lowest body line |
| 1 | orphaned_heading | the heading has no body line after it |
| 1 | excessive_whitespace, page_break_defects | not applicable: single final page |
| 2 | contact_details | the profile name or e-mail is not an extracted line |
| 2 | headings | the template heading is missing |
| 2 | reading_order | warning, contact, heading, target, every assertion and footer not found in order (whitespace-insensitive, so wrapped tokens still match) |
| 2 | unicode | U+FFFD, ligature or mojibake not in the inputs, or non-NFC text |
| 2 | placeholders | `{{...}}`, TODO, TBD, `[Company]`-style brackets, lorem ipsum |
| 2 | dates | an extracted year or month-year absent from the inputs |
| 2 | target | letter target line differs from the job snapshot |
| 2 | links | not applicable: the profile has no links |

A job may state `required_formats` (`pdf`, `docx`, `txt`, `html`). Anything but
`pdf` gives `status=blocked_input` naming the unsupported formats: no other format
is produced or approximated. Status is `mechanical_passed`, `blocked_quality`
(with `failed_checks`) or `blocked_input`, and `ready` is always false. The model
visual review of page images is `not_run`; page fit, independent review, repair
and manifest gates stay separate. Deleting a source scrubs the stored results of
the drafts that used it. Glyph support is still the Windows-1252 Latin set:
multilingual rendering needs a licensed, pinned Unicode font and remains open.

Tests: `tests/test_jw_verification.py` proves every gate-1 check and the gate-2
contact, order, target, placeholder, unicode and date checks fail on drawn defect
PDFs, and that a drawn clean baseline passes. A 2026-11-04 sample letter was
rasterized with Poppler and inspected: no clipping, overlap or missing text.

## Pages, Unicode font and visual review (JW-09, private-fixed@3, mechanical-gates@2)

**Page policy.** A job may state `page_limit` (1, 2 or 3). The default is 2 for a CV and 1 for a
letter. Content that does not fit raises `page_fit_conflict`; the font never shrinks and nothing
is dropped. Each page carries `Private review only. Quality gates incomplete. Page n of N.`
Pagination rules:

- A heading stays with the start of the block after it.
- A block of six lines or fewer never splits.
- A longer block splits only with at least two lines on each side of the break.

**Gates across pages.**

| Check | Fails when |
|---|---|
| compiles | page count outside 1..`page_limit` |
| footer_collision | a page's footer is missing, duplicated, colliding, or not its exact `Page n of N` |
| orphaned_heading | a heading is the last body line of any page |
| excessive_whitespace | a non-final page leaves more than 35% of its content area blank |
| page_break_defects | a block's first line sits alone at a page foot, or its last line alone at the next page's head |

Block boundaries come from the expected content, never from the renderer's layout report. The
extracted text leaves footers out, so a block wrapped across a break still matches reading order.
One page still reports the two page checks as `not_applicable`.

**Unicode font (EC-DOC-03).** `render-font` pins an owner-supplied local TrueType file by SHA-256
in `controls`. Helvetica with Windows-1252 stays the default. ReportLab embeds a subset of the
pinned font. Renders fail closed:

- `toolchain_version` when the file's hash changes.
- `unsupported_glyph` when the font has no printing glyph for a character. A cmap entry that maps
  to `.notdef`, or that has no advance width, does not count as coverage. Bundled Vera maps `ż`
  that way and printed nothing before this rule.
- `unsupported_glyph` for scripts that need shaping or right-to-left layout: Hebrew, Arabic,
  Syriac, Thaana, Indic, Thai, Lao, Tibetan, Myanmar, Khmer, presentation forms and combining marks.
  `drawString` does neither shaping nor bidi, so the template refuses these scripts rather than
  print broken text.

Licensing of a pinned font is the owner's. Only private drafts embed it, and no font file is
committed. Tests use ReportLab's bundled Bitstream Vera, which is redistributable.

**Visual review.** Gates 1-2 report `visual_review` as `pending_review_task`. The page images go to
the independent review task, and `draft-readiness` requires that review (see `visual.py`, JW-25).

**Model visual review, 2026-11-07.** Inputs:

- A synthetic CV of 8 long assertions with a 2-page limit, in Helvetica.
- A letter whose name mixes Greek, Cyrillic and CJK, rendered in a locally pinned Arial Unicode
  (not committed).

Both passed gates 1-2. The pages were rasterised by `visual.rasterise` and inspected:

- No clipping, overlap or missing glyphs.
- Correct page footers.
- No block split across the CV page break, and no orphaned heading.
- Non-Latin glyphs drawn correctly.
- CV page 1 ends about four lines early, because a six-line block moved whole. That is within the
  whitespace limit.
