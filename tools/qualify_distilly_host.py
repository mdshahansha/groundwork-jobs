"""Save a host-generated Distilly owner profile with the pinned upstream writer and check it.

Run only after reviewing the downloaded writer: it executes upstream code. Steps: verify the writer
hash, check the profile against the builder contract, run `save` under a temporary
DISTILLY_OWNER_HOME (no host linking), then map the saved file to claims cut from the source in a
throwaway jw workspace. Lines containing any --forbid text must never become claims.
"""

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from jw.contracts import canonical
from jw.integrations import check_host_profile, map_profile
from jw.workspace import Workspace

PIN = "0afc45c29c360ba7bc8260f1bb0bf34e9155f4fa"
WRITER_SHA256 = "09fc5a8e3bd2ccd09d147fa2d422e853525bd30fee26b5a5da38c34ae9c12f7b"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--writer", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--forbid", action="append", default=[])
    args = parser.parse_args()
    writer = args.writer.resolve()
    if hashlib.sha256(writer.read_bytes()).hexdigest() != WRITER_SHA256:
        parser.error("Writer hash differs from the reviewed upstream pin; execution refused.")
    structure = check_host_profile(args.profile.read_text(encoding="utf-8"))
    source = args.source.read_bytes()
    with tempfile.TemporaryDirectory(prefix="jw-distilly-host-") as temporary:
        root = Path(temporary)
        environment = dict(os.environ, DISTILLY_OWNER_HOME=str(root / "owner"))
        subprocess.run([sys.executable, str(writer), "save", "--profile", str(args.profile)],
                       env=environment, check=True, capture_output=True, timeout=30)
        saved = (root / "owner" / "profile.md").read_text(encoding="utf-8")
        ws = Workspace(root / "ws", create=True)
        try:
            source_id = ws.import_source(source, sensitivity="public")["source_id"]
            evidence, offset = [], 0
            for line in source.decode("utf-8").splitlines(keepends=True):
                body = line.strip()
                if body and not any(f in body for f in args.forbid):
                    start = offset + line.index(body)
                    evidence.append({"text": body, "claim_id": ws.add_claim(source_id, start, start + len(body))["claim_id"]})
                offset += len(line)
        finally:
            ws.close()
    result = map_profile(saved, evidence)
    leaked = [f for f in args.forbid if any(f in a["text"] for a in result["assertions"])]
    passed = bool(result["assertions"]) and not leaked
    print(canonical({"pin": PIN, "host_inference": "exercised", "host_linking": False, "structure": structure,
                     "mapped": len(result["assertions"]), "unassessed_lines": result["unassessed_lines"],
                     "forbidden_leaked": leaked, "passed": passed}))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
