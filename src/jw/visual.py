"""JW-25 gate 3: page images for the independent visual review, and the readiness decision.

Pages are rasterised by pypdfium2 (optional `visual` extra) in a separate isolated interpreter
with the same limits as PDF parsing. Images go to `review-images/<review task>/` inside the
workspace, never into the packet: the packet carries each file's path, size and SHA-256 so the
host can attach them and anyone can check they were not swapped. Erasing a source deletes the
images of every task it erased.

A draft is `ready` only when all of these hold for its current inputs: gates 1-2 passed on its
latest verification, an independent review that was given page images completed, and that
review has no critical or major finding.
"""

import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from .contracts import require

FOLDER = "review-images"
SCALE = 1.5
MAX_PAGES = 2
WORKER = r"""
import base64, json, struct, sys, zlib
try:
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
except (ImportError, ValueError, OSError):
    pass
try:
    import pypdfium2 as pdfium
except ImportError:
    print(json.dumps({"error": "rasteriser_unavailable"})); sys.exit(0)

def png(width, height, stride, buffer):
    # 8-bit greyscale PNG written by hand, so no imaging library is needed.
    raw = b"".join(b"\x00" + bytes(buffer[y * stride:y * stride + width]) for y in range(height))
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))

try:
    doc = pdfium.PdfDocument(sys.stdin.buffer.read())
    pages = []
    for index in range(min(len(doc), int(sys.argv[2]))):
        bitmap = doc[index].render(scale=float(sys.argv[1]), grayscale=True)
        info = bitmap.get_info()
        data = png(info.width, info.height, info.stride, bitmap.buffer)
        pages.append({"page": index + 1, "width": info.width, "height": info.height,
                      "png": base64.b64encode(data).decode()})
    print(json.dumps({"pages": pages, "count": len(doc)}))
except Exception:
    print(json.dumps({"error": "unreadable"}))
"""

def rasterise(pdf, timeout=60):
    """[{page, width, height, png bytes}] or None when the rasteriser is not installed."""
    require(isinstance(pdf, bytes) and pdf.startswith(b"%PDF"), "invalid_schema", "Rasterising needs PDF bytes.")
    with tempfile.TemporaryDirectory(prefix="jw-raster-") as scratch:
        try:
            done = subprocess.run([sys.executable, "-I", "-c", WORKER, str(SCALE), str(MAX_PAGES)], input=pdf,
                                  capture_output=True, timeout=timeout, cwd=scratch, env={}, check=False)
        except subprocess.TimeoutExpired:
            require(False, "parser_limit", "Rasterising exceeded its time limit.")
    try:
        result = json.loads(done.stdout.decode("utf-8").strip().splitlines()[-1])
    except (ValueError, IndexError, UnicodeError):
        result = {"error": "unreadable"}
    if result.get("error") == "rasteriser_unavailable":
        return None
    require("error" not in result, "toolchain_missing", "Page rasterising failed (" + str(result.get("error")) + ").")
    return [dict(page, png=base64.b64decode(page["png"])) for page in result["pages"]]


def store_images(root, task_key, pages):
    folder = Path(root) / FOLDER / task_key
    folder.mkdir(parents=True, exist_ok=True)
    listed = []
    for page in pages:
        path = folder / f"page-{page['page']}.png"
        path.write_bytes(page["png"])
        listed.append({"page": page["page"], "path": str(path), "media_type": "image/png",
                       "width": page["width"], "height": page["height"], "bytes": len(page["png"]),
                       "sha256": hashlib.sha256(page["png"]).hexdigest()})
    return listed


def purge_erased(ws):
    """Remove page images whose task content was erased (FR-PRF-07)."""
    folder = ws.store.root / FOLDER
    if not folder.is_dir():
        return 0
    erased = {r[0] for r in ws.db.execute("SELECT fingerprint FROM tasks WHERE state='erased'")}
    removed = 0
    for child in folder.iterdir():
        if child.name.removesuffix("-review") in erased:
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return removed


def readiness(tasks, draft_id):
    from .tasks import BLOCKING, DRAFT_KINDS
    from .contracts import digest

    ws, db = tasks.ws, tasks.db
    draft = ws.store.one("tasks", draft_id)
    require(draft["kind"] in DRAFT_KINDS, "invalid_schema", "Readiness applies to CV and letter drafts.")
    gates, missing = {}, []
    current = draft["state"] == "completed" and draft["dependency"] == digest(ws.dependencies(draft["job_id"]))
    gates["inputs_current"] = current
    row = db.execute("SELECT status FROM verifications WHERE task_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                     (draft_id,)).fetchone()
    gates["mechanical"] = row["status"] if row else "not_run"
    review_state, findings, images = "not_run", None, False
    for review in db.execute("SELECT packet, output, state FROM tasks WHERE kind='review' AND job_id=? "
                             "ORDER BY created_at DESC", (draft["job_id"],)).fetchall():
        packet = json.loads(review["packet"] or "{}")
        if packet.get("draft_task_id") != draft_id:
            continue
        images = isinstance(packet.get("rendered", {}).get("page_images"), list)
        review_state = review["state"]
        if review["state"] == "completed":
            findings = json.loads(review["output"])["findings"]
        break
    gates["visual_review"] = {"state": review_state, "page_images_supplied": images}
    blocking = [f for f in findings or [] if f["severity"] in BLOCKING]
    gates["blocking_findings"] = len(blocking)
    if not current:
        missing.append("inputs_changed_or_draft_incomplete")
    if gates["mechanical"] != "mechanical_passed":
        missing.append("mechanical_gates")
    if review_state != "completed":
        missing.append("independent_review")
    elif not images:
        missing.append("page_images_not_reviewed")
    if blocking:
        missing.append("blocking_findings")
    return {"draft_id": draft_id, "ready": not missing, "gates": gates, "missing": missing}
