#!/usr/bin/env python3
"""Guarded invocation of the existing, read-only verified corpus export."""
import os
from pathlib import Path
import re
import subprocess
import sys

from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_DATABASE = "app_peb68ccd10bc4e4ea3b43852"
CA_CERT = "/etc/ssl/certs/ca-certificates.crt"


def export(corpus, output):
    if not re.fullmatch(r"[a-f0-9]{64}", corpus):
        raise ValueError("invalid corpus")
    config = conninfo_to_dict(os.environ.get("POLYGRES_DIRECT_URL", ""))
    if (not config.get("host") or config.get("dbname") != EXPECTED_DATABASE
            or config.get("service") or config.get("hostaddr")
            or os.environ.get("PGSERVICE") or os.environ.get("PGHOSTADDR")):
        raise ValueError("database identity is not configured")
    url = make_conninfo(os.environ["POLYGRES_DIRECT_URL"], sslmode="verify-full", sslrootcert=CA_CERT,
                        connect_timeout=10, options="-c default_transaction_read_only=on -c statement_timeout=120000 -c lock_timeout=1000")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    environment["POLYGRES_DIRECT_URL"] = url
    result = subprocess.run([sys.executable, str(ROOT / "scripts/document-evidence-db.py"), "export",
                             "--expected-database", EXPECTED_DATABASE, "--corpus", corpus, "--out", output],
                            env=environment, capture_output=True, text=True, timeout=160, check=False)
    if result.returncode:
        raise ValueError("verified read-only corpus export unavailable")
    return result.stdout


if __name__ == "__main__":
    try:
        if len(sys.argv) != 3:
            raise ValueError("invalid invocation")
        print(export(sys.argv[1], sys.argv[2]), end="")
    except Exception:
        print("verified read-only corpus export unavailable", file=sys.stderr)
        sys.exit(1)
