"""Bounded, in-memory CSV utilities for the independent portion of JW-22.

The caller owns original-byte storage and repeat-import persistence. Normalized
exports are not archival copies. No date mapping, partial import, or application
deduplication is performed here. Invalid input raises ValueError (TypeError for
non-bytes input). CSV uses commas, doubled quotes, and CR/LF/CRLF record endings.
"""

import csv
import hashlib
import io


MAX_CSV_BYTES = 5 * 1024 * 1024


def archive_identity(raw: bytes) -> str:
    """Return the SHA-256 hex digest of the exact original bytes."""
    if not isinstance(raw, bytes):
        raise TypeError("raw must be bytes")
    return hashlib.sha256(raw).hexdigest()


def _records(text):
    """Parse strict CSV without changing csv's process-global field limit."""
    row, cell = [], []
    state = "start"
    pending = False
    i = 0
    while i < len(text):
        char = text[i]
        pending = True
        if state == "quoted":
            if char == '"':
                state = "closed"
            else:
                cell.append(char)
        elif state == "closed" and char == '"':
            cell.append('"')
            state = "quoted"
        elif char == ',' or char in '\r\n':
            row.append(''.join(cell))
            cell = []
            state = "start"
            if char != ',':
                yield row
                row = []
                pending = False
                if char == '\r' and i + 1 < len(text) and text[i + 1] == '\n':
                    i += 1
        elif state == "closed":
            raise ValueError("Unexpected content after closing CSV quote")
        elif char == '"':
            if state != "start":
                raise ValueError("Quote inside unquoted CSV field")
            state = "quoted"
        else:
            cell.append(char)
            state = "unquoted"
        i += 1
    if state == "quoted":
        raise ValueError("Unterminated CSV quoted field")
    if pending:
        row.append(''.join(cell))
        yield row


def normalize_csv(raw: bytes, encoding='utf-8-sig') -> dict:
    """Decode strictly and return headings, rows, encoding, and raw sha256.

    Headings and each row are positional lists of strings. Unknown/duplicate
    headings, whitespace, empty cells, and original date strings are retained.
    Encoding records the caller's selected codec; no encoding is guessed.
    Empty files, NULs, invalid quotes, and inconsistent widths are rejected.
    A trailing record terminator does not create an extra row.
    """
    if not isinstance(raw, bytes):
        raise TypeError("raw must be bytes")
    if len(raw) > MAX_CSV_BYTES:
        raise ValueError("CSV exceeds 5 MiB")
    if not isinstance(encoding, str):
        raise ValueError("encoding must name a text codec")
    try:
        text = raw.decode(encoding, errors='strict')
    except (LookupError, UnicodeError) as exc:
        raise ValueError("CSV cannot be decoded with the selected encoding") from exc
    if '\x00' in text:
        raise ValueError("NUL is not allowed in CSV")
    records = _records(text)
    headings = next(records, None)
    if headings is None:
        raise ValueError("CSV requires a heading record")
    rows = []
    for number, row in enumerate(records, start=2):
        if len(row) != len(headings):
            raise ValueError(f"CSV record {number} has inconsistent column count")
        rows.append(row)
    return dict(headings=headings, rows=rows, encoding=encoding,
                sha256=archive_identity(raw))


def _safe_cell(cell):
    # Prefix the original value, preserving its whitespace and contents.
    # Tabs/CR/LF in the leading whitespace are risky even without a formula.
    stripped = cell.lstrip()
    leading = cell[:len(cell) - len(stripped)]
    if stripped.startswith(('=', '+', '-', '@')) or any(
            char in leading for char in '\t\r\n'):
        return "'" + cell
    return cell


def export_safe_csv(normalized) -> bytes:
    """Return BOM-prefixed UTF-8 CSV with CRLF records and inert formula cells.

    Protect headings as well as data. Already prefixed cells remain unchanged,
    so export/parse/export is stable. Input is never mutated; metadata refers
    to the original import and is not emitted as CSV columns.
    """
    if not isinstance(normalized, dict):
        raise ValueError("normalized must be a dict")
    headings = normalized.get('headings')
    rows = normalized.get('rows')
    if not isinstance(headings, list) or not headings or not isinstance(rows, list):
        raise ValueError("headings and rows must be positional lists")
    output = io.StringIO(newline='')
    writer = csv.writer(output, lineterminator='\r\n')
    for row in [headings, *rows]:
        if not isinstance(row, list) or len(row) != len(headings):
            raise ValueError("Inconsistent export column count")
        if any(not isinstance(cell, str) or '\x00' in cell for cell in row):
            raise ValueError("CSV cells must be strings without NUL")
        writer.writerow([_safe_cell(cell) for cell in row])
    return output.getvalue().encode('utf-8-sig')
