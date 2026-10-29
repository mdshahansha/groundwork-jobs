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
