# Report images: design system

The images in [STRATEGY_REPORT.md](../STRATEGY_REPORT.md) and the top-level
[README](../../../README.md) come from one generator and one set of tokens, so every step reads
the same way. Edit [build_diagrams.py](build_diagrams.py), never the SVG files, then rebuild:

```bash
python3 docs/product/images/build_diagrams.py
```

Standard library only. The output is plain SVG with system fonts, a `<title>` and a `<desc>`,
so it renders on GitHub and reads aloud in screen readers.

| Image | Shows |
| --- | --- |
| [overview-pipeline.svg](overview-pipeline.svg) | All seven steps with their state, and where 2,000 posts went in the 2026-11-07 run |
| [step-1-hiring-signals.svg](step-1-hiring-signals.svg) | Search cards and e-mail-only intake, versus person-first queries and a signal classifier |
| [step-2-person.svg](step-2-person.svg) | Display-name authors, versus a people record and an authenticity class |
| [step-3-contact.svg](step-3-contact.svg) | First e-mail in the text, versus a route hierarchy with provenance |
| [step-4-opportunity.svg](step-4-opportunity.svg) | Regex fields and a degenerate score, versus extraction and a 10-factor score |
| [step-5-resume.svg](step-5-resume.svg) | One fixed PDF, versus gated variants and per-lead tailoring |
| [step-6-email.svg](step-6-email.svg) | Checker gaps, versus a signal-first anatomy and a stricter checker |
| [step-7-approval-tracking.svg](step-7-approval-tracking.svg) | Unlinked sends, versus linked outcomes, suppression and metrics |

## How to read a step image

1. **Header**: step number, name, the vision it serves, and a state chip (`PARTIAL`, `MISSING`,
   `BUILT, NOT WIRED`).
2. **Left panel, NOW**: what the code does today, top to bottom in pipeline order. Each card
   ends with the file and line that proves it.
3. **Right panel, TARGET**: what to build, in build order. Each card ends with its
   recommendation ID and priority from the report.
4. **Footer**: the success metric that proves the step works, and the recommendations in
   priority order.

## Tokens

| Group | Token | Value | Use |
| --- | --- | --- | --- |
| Colour | `ink` | `#0F172A` | Titles, numbers |
| Colour | `text` | `#1E293B` | Body text |
| Colour | `muted` | `#64748B` | Captions, file references |
| Colour | `line` | `#94A3B8` | Arrows and connectors |
| Colour | `border` | `#E2E8F0` | Canvas, panel and footer borders |
| Colour | `surface` / `panel` | `#FFFFFF` / `#F8FAFC` | Canvas / panel fill |
| Colour | `brand` | `#3538CD` | Step badges, funnel bars |
| Type | `title` | 24 px, 700 | Step title |
| Type | `subtitle` | 14 px | Vision line |
| Type | `node` | 14 px, 700 | Card title |
| Type | `body` | 12.5 px | Card text |
| Type | `ref` | 11 px, monospace | File references, recommendation IDs |
| Type | `chip` | 10.5 px, 700, tracked | Kind and state labels |
| Space | `SPACE` | 8 px | Base grid; every gap is a multiple |
| Radius | `canvas` / `panel` / `node` / `chip` | 16 / 14 / 10 / 6 px | Corners |

## Components

**Node card** (kind variants). The label is always printed, so colour is never the only cue.

| Kind | Accent | Label | Use when |
| --- | --- | --- | --- |
| `now` | slate `#475569` | NOW | Current behaviour that is acceptable |
| `gap` | red `#B42318` | GAP | A defect, contradiction or missing piece |
| `reuse` | blue `#175CD3` | REUSE | Code that exists and should be reused, not rebuilt |
| `new` | green `#067647` | NEW | Something to build |
| `rule` | amber `#B54708` | RULE | A policy, gate or owner decision |
| `never` | red `#B42318` | NEVER | Something the product must not do |

Card properties: `title` (required), `body` (list of lines), `bars` (list of label and value,
drawn as a bar chart), `max`, `fmt`, `ref` (file:line or recommendation ID).

**State chip**: `partial` (amber), `missing` (red), `disconnected` (blue, "BUILT, NOT WIRED").

**Panel**: titled chip, cards in a vertical flow joined by arrows. Left panel uses the `gap`
accent for its title, right panel the `new` accent.

**Footer**: success metric (bold) and recommendations, then the colour key.

## Rules

| Do | Don't |
| --- | --- |
| Put a file:line or recommendation ID on every card | Add a claim the report does not make |
| Keep one idea per card, at most five lines of body | Shrink fonts to fit more text; split the card instead |
| Order cards by pipeline order (NOW) or build order (TARGET) | Use colour alone to carry meaning |
| Keep personal data out: no names, e-mails or phone numbers | Name rival products in an image |
| Rebuild from the script after editing the report | Hand-edit an SVG |
