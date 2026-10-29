"""Exercise the reviewed pinned owner-profile writer with synthetic data only.

Download tools/owner_profile.py from the documented upstream SHA separately.
This is the storage/output contract probe, not a host-model inference test.
"""

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from jw.contracts import canonical
from jw.integrations import map_profile

PIN = "0afc45c29c360ba7bc8260f1bb0bf34e9155f4fa"
WRITER_SHA256 = "09fc5a8e3bd2ccd09d147fa2d422e853525bd30fee26b5a5da38c34ae9c12f7b"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--writer", required=True, type=Path)
    args = parser.parse_args()
    writer = args.writer.resolve()
    if hashlib.sha256(writer.read_bytes()).hexdigest() != WRITER_SHA256:
        parser.error("Writer hash differs from the reviewed upstream pin; execution refused.")
    with tempfile.TemporaryDirectory(prefix="jw-distilly-probe-") as temporary:
        root = Path(temporary)
        source = root / "input.md"
        source.write_text("# Synthetic owner\n## Always-on summary\n- Built Python services.\n"
                          "## Evidence\n- Managed 50 people.\n", encoding="utf-8")
        # No host-link operation. Upstream's explicit profile-root override
        # confines this save operation without changing the user's HOME.
        environment = dict(os.environ, DISTILLY_OWNER_HOME=str(root / "owner"))
        subprocess.run([sys.executable, str(writer), "save", "--profile", str(source)],
                       env=environment, check=True, capture_output=True, timeout=30)
        output = (root / "owner" / "profile.md").read_text(encoding="utf-8")
        expected = [{"text": "Built Python services.", "claim_id": "synthetic-claim"}]
        result = map_profile(output, expected)
        if result["assertions"] != expected or result["unassessed_lines"] != 1:
            raise RuntimeError("Pinned writer output did not satisfy evidence mapping.")
        print(canonical({"pin": PIN, "writer_sha256": WRITER_SHA256,
                         "storage_mapping": "passed", "host_inference": "not_exercised",
                         "host_linking": False, "result": result}))


if __name__ == "__main__":
    main()
