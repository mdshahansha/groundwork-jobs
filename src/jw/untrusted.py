"""JW-18: untrusted input boundaries (FR-SEC-04, FR-SEC-06).

- PDF text is parsed in a separate isolated interpreter with CPU, memory, file-size and wall
  time limits, an empty environment and a scratch working directory. Only page text is read:
  JavaScript, forms, attachments and embedded files are never touched.
- Archives are inspected before anything is read: member count, total and per-member size,
  compression ratio, depth 1 (no nested archives), no traversal, symlinks ignored, no encryption.
- Images need OCR, which is not available: refused with a stable code, never guessed at.
- URLs are checked before any fetch: scheme, credentials, port, and every resolved address
  against private, loopback, link-local, metadata and reserved ranges, on each redirect hop.
- Text that reaches HTML is escaped, quotes included.
"""

import html
import ipaddress
import json
from pathlib import PurePosixPath
import socket
import stat
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
import zipfile
from io import BytesIO

from .contracts import require

PDF_TIMEOUT = 30
PDF_MAX_PAGES = 50
ARCHIVE_MAX_MEMBERS = 20
ARCHIVE_MAX_TOTAL = 5_000_000
ARCHIVE_MAX_RATIO = 100
ARCHIVE_TEXT = {".txt", ".md"}
NESTED = {".zip", ".gz", ".tgz", ".tar", ".7z", ".rar", ".bz2", ".xz", ".jar"}
MAX_REDIRECTS = 5
METADATA = {ipaddress.ip_address("169.254.169.254"), ipaddress.ip_address("fd00:ec2::254"),
            ipaddress.ip_address("100.100.100.200")}
IMAGE_MAGIC = (b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"II*\x00", b"MM\x00*", b"RIFF")

# Runs under `python -I`: no site-packages from the user dir, no cwd on sys.path, no env.
WORKER = r"""
import json, sys
try:
    import resource
    for limit, value in ((resource.RLIMIT_CPU, 10), (resource.RLIMIT_FSIZE, 0)):
        resource.setrlimit(limit, (value, value))
    try:
        resource.setrlimit(resource.RLIMIT_AS, (768 << 20, 768 << 20))
    except (ValueError, OSError):
        pass
except ImportError:
    pass
from io import BytesIO
try:
    from pypdf import PdfReader
except ImportError:
    print(json.dumps({"error": "parser_unavailable"})); sys.exit(0)
data = sys.stdin.buffer.read()
try:
    reader = PdfReader(BytesIO(data), strict=False)
    if reader.is_encrypted:
        print(json.dumps({"error": "encrypted"})); sys.exit(0)
    if len(reader.pages) > int(sys.argv[1]):
        print(json.dumps({"error": "too_many_pages"})); sys.exit(0)
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    print(json.dumps({"text": text}))
except Exception:
    print(json.dumps({"error": "unreadable"}))
"""


def extract_pdf_text(raw, python=None, timeout=PDF_TIMEOUT):
    require(isinstance(raw, bytes) and raw.startswith(b"%PDF"), "unsupported_format", "Not a PDF.")
    with tempfile.TemporaryDirectory(prefix="jw-pdf-") as scratch:
        try:
            done = subprocess.run([python or sys.executable, "-I", "-c", WORKER, str(PDF_MAX_PAGES)],
                                  input=raw, capture_output=True, timeout=timeout, cwd=scratch,
                                  env={}, check=False)
        except subprocess.TimeoutExpired:
            require(False, "parser_limit", "PDF parsing exceeded its time limit.")
    try:
        result = json.loads(done.stdout.decode("utf-8").strip().splitlines()[-1])
    except (ValueError, IndexError, UnicodeError):
        result = {"error": "limit" if done.returncode else "unreadable"}
    error = result.get("error")
    require(error != "parser_unavailable", "unsupported_format", "PDF parsing needs pypdf installed.")
    require(error != "limit", "parser_limit", "PDF parsing exceeded its resource limits.")
    require(error is None, "unsupported_format", "PDF could not be parsed (" + str(error) + ").")
    text = result["text"].replace("\x00", "")
    require(text.strip(), "unsupported_format", "PDF has no extractable text; scanned pages need OCR.")
    return text


def refuse_image(raw):
    require(not raw.startswith(IMAGE_MAGIC), "ocr_unavailable",
            "Images and scanned pages need OCR, which is not available; paste the text instead.")


def archive_members(raw):
    """Inspect, then read. Returns ([(name, bytes)], [ignored names with reasons])."""
    try:
        archive = zipfile.ZipFile(BytesIO(raw))
        infos = archive.infolist()
    except (zipfile.BadZipFile, OSError, ValueError):
        require(False, "unsupported_format", "Archive is not a readable ZIP.")
    require(len(infos) <= ARCHIVE_MAX_MEMBERS, "archive_limit", "Archive has too many members.")
    total = sum(info.file_size for info in infos)
    require(total <= ARCHIVE_MAX_TOTAL, "archive_limit", "Archive expands beyond the size limit.")
    members, ignored = [], []
    for info in infos:
        name = info.filename
        path = PurePosixPath(name.replace("\\", "/"))
        require(bool(path.parts) and not path.is_absolute() and ".." not in path.parts and ":" not in path.parts[0],
                "archive_traversal", "Archive member path escapes the archive.")
        require(not info.flag_bits & 0x1, "archive_encrypted", "Encrypted archive members are refused.")
        if info.is_dir():
            continue
        if stat.S_ISLNK(info.external_attr >> 16):
            ignored.append({"name": name, "reason": "symlink"})
            continue
        suffix = path.suffix.lower()
        require(suffix not in NESTED, "archive_nested", "Nested archives are refused (depth 1).")
        require(info.compress_size == 0 or info.file_size / info.compress_size <= ARCHIVE_MAX_RATIO,
                "archive_limit", "Archive member compression ratio is too high.")
        if suffix not in ARCHIVE_TEXT | {".pdf"}:
            ignored.append({"name": name, "reason": "unsupported_type"})
            continue
        with archive.open(info) as stream:
            data = stream.read(info.file_size + 1)
        require(len(data) <= info.file_size, "archive_limit", "Archive member is larger than declared.")
        members.append((name, data))
    return members, ignored


def _blocked(address):
    if address.version == 6 and address.ipv4_mapped:
        address = address.ipv4_mapped
    return (address in METADATA or address.is_private or address.is_loopback or address.is_link_local or
            address.is_multicast or address.is_reserved or address.is_unspecified or
            (address.version == 4 and address in ipaddress.ip_network("100.64.0.0/10")))


def check_url(url, user_supplied=False, resolve=None):
    """Validate one hop. `resolve(host, port)` returns IP strings; default uses DNS."""
    require(isinstance(url, str) and len(url) <= 2000 and url.isprintable(), "unsafe_url", "URL is malformed.")
    parts = urlsplit(url)
    allowed = ("https", "http") if user_supplied else ("https",)
    require(parts.scheme in allowed, "unsafe_url", "Only https (or http for URLs you typed) is allowed.")
    require(not parts.username and not parts.password, "unsafe_url", "Credentials in URLs are refused.")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        require(False, "unsafe_url", "URL port is invalid.")
    host = parts.hostname
    require(bool(host), "unsafe_url", "URL has no host.")
    require(port in (80, 443), "unsafe_url", "Only the standard web ports are allowed.")
    if resolve is None:
        def resolve(name, number):
            return [info[4][0] for info in socket.getaddrinfo(name, number, proto=socket.IPPROTO_TCP)]
    try:
        addresses = [ipaddress.ip_address(item.split("%")[0]) for item in resolve(host, port)]
    except (OSError, ValueError):
        require(False, "unsafe_url", "Host does not resolve.")
    require(bool(addresses), "unsafe_url", "Host does not resolve.")
    require(not any(_blocked(a) for a in addresses), "unsafe_url",
            "Host resolves to a private, loopback, link-local or metadata address.")
    return {"url": url, "host": host, "addresses": [str(a) for a in addresses]}


def check_redirects(chain, user_supplied=False, resolve=None):
    """Every hop is re-validated; the first is the only one that may be user-supplied http."""
    require(isinstance(chain, list) and 0 < len(chain) <= MAX_REDIRECTS + 1, "unsafe_url",
            "Too many redirects.")
    return [check_url(url, user_supplied and i == 0, resolve) for i, url in enumerate(chain)]


def html_text(value):
    """Escape untrusted text for an HTML text node or quoted attribute."""
    return html.escape(str(value), quote=True)
