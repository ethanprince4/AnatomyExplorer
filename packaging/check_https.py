"""Run the real frozen updater transport with nonexistent default OpenSSL CA paths.

Usage: python packaging/check_https.py PATH_TO_FROZEN_EXECUTABLE [--report OUTPUT]
No UI or update activation is started. Only bounded public stable release reads.
"""
import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    executable = args.executable.resolve()
    with tempfile.TemporaryDirectory(prefix="AnatomyExplorer-https-") as d:
        root = Path(d).resolve()
        report = root / "https.json"
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", LOCALAPPDATA=str(root / "profile"),
                   AE_TEST_SETTINGS_DIR=str(root / "settings"),
                   SSL_CERT_FILE=str(root / "nonexistent-ca.pem"),
                   SSL_CERT_DIR=str(root / "nonexistent-ca-directory"),
                   REQUESTS_CA_BUNDLE=str(root / "nonexistent-requests-ca.pem"),
                   CURL_CA_BUNDLE=str(root / "nonexistent-curl-ca.pem"))
        # Never publish subprocess output: OS/network exceptions may carry paths
        # or signed CDN query strings. The client writes a sanitized JSON report.
        try:
            completed = subprocess.run([str(executable), "--https-check", "--report", str(report)],
                                       env=env, capture_output=True, timeout=180)
        except subprocess.TimeoutExpired:
            raise SystemExit("Frozen HTTPS check timed out") from None
        except OSError:
            raise SystemExit("Frozen HTTPS check could not start") from None
        if not report.is_file():
            raise SystemExit("Frozen HTTPS check produced no report")
        result = json.loads(report.read_text(encoding="utf-8"))
        print(json.dumps(result, indent=2))
        if args.report:
            args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
        if completed.returncode or not result.get("success"):
            raise SystemExit("Frozen HTTPS verification failed; see sanitized report")
        assert result["frozen"] and result["tls"]["bundled_ca"]
        assert result["tls"]["certificate_required"] and result["tls"]["hostname_verified"]
        assert result["manifest"]["api_digest_verified"] and result["chunk"]["integrity_verified"]
        assert result["chunk"]["range_verified"] and result["installer"]["range_verified"]
        assert result["installer"]["downloaded_bytes"] == 64
        assert not (root / "profile").exists() and not (root / "settings").exists()


if __name__ == "__main__":
    main()
