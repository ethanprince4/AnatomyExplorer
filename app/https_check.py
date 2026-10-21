"""Bounded, read-only updater HTTPS check for source and packaged applications.

Only the fixed public Cloudflare feed is accessed. Reports contain no local paths,
proxy credentials, redirect query strings, update stores, or study information.
"""
import argparse
import json
import ssl
import sys
import urllib.error
from pathlib import Path

import certifi

from . import updater as u
from .tls import https_context

PLATFORMS = ("windows-x64", "macos-arm64")
REPORT_SCHEMA = 2
FAILURE_STAGES = frozenset({"tls_context", "discovery", "chunk"})


def at_stage(stage, operation):
    """Preserve the original exception while retaining a safe request label."""
    try:
        return operation()
    except Exception as exc:
        exc.https_check_stage = stage
        raise


def check(platform=None, channel="stable"):
    source = at_stage("tls_context", lambda: u.CloudflareSource(platform=platform, channel=channel))
    context = at_stage("tls_context", https_context)
    ca = Path(certifi.where())
    frozen = bool(getattr(sys, "frozen", False))
    bundled = frozen and ca.absolute().is_relative_to(Path(sys._MEIPASS).absolute())
    report = {
        "schema": REPORT_SCHEMA,
        "frozen": frozen,
        "platform": source.platform,
        "tls": {
            "ca_source": "certifi",
            "certifi_version": certifi.__version__,
            "ca_sha256": u.file_sha(ca),
            "bundled_ca": bundled,
            "trusted_ca_count": context.cert_store_stats()["x509_ca"],
            "certificate_required": context.verify_mode == ssl.CERT_REQUIRED,
            "hostname_verified": context.check_hostname,
        },
    }
    # Exercise the application's real channel -> catalog -> manifest discovery,
    # including both content hashes and the exact metadata/pack bindings.
    manifest = at_stage("discovery", source.latest)
    if manifest is None or not manifest["blobs"]:
        error = u.UpdateError("Published channel has no incremental update payload")
        error.https_check_stage = "discovery"
        raise error
    report["channel"] = {"name": source.channel, "url": source.channel_url}
    report["catalog"] = {"url": source.catalog_url, "integrity_verified": True}
    report["manifest"] = {
        "url": source.manifest_url,
        "version": manifest["version"],
        "sha256": source.manifest_digest,
        "bytes": source.manifest_size,
        "catalog_digest_verified": True,
    }

    # The smallest real blob exercises a bounded 206 response and decompression
    # using the same transport and raw-chunk verification as an update download.
    digest, blob = min(manifest["blobs"].items(), key=lambda item: (item[1]["size"], item[0]))
    raw = at_stage("chunk", lambda: source.chunk(blob, manifest["packs"][blob["pack"]]))
    at_stage("chunk", lambda: u.unpack_chunk(raw, blob["raw_size"], digest))
    start, end = blob["offset"], blob["offset"] + blob["size"] - 1
    report["chunk"] = {
        "url": source.urls[blob["pack"]],
        "content_range": f"bytes {start}-{end}/{manifest['packs'][blob['pack']]}",
        "downloaded_bytes": len(raw),
        "raw_bytes": blob["raw_size"],
        "raw_sha256": digest,
        "range_verified": True,
        "integrity_verified": True,
    }

    report["success"] = True
    return report


def failure_category(exc):
    """Classify failures without publishing exception strings containing URLs/paths."""
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, ssl.SSLCertVerificationError):
        return "certificate_verification_failed"
    if isinstance(reason, ssl.SSLError):
        return "tls_failed"
    if isinstance(exc, urllib.error.HTTPError):
        return f"http_{exc.code}"
    if isinstance(exc, u.UpdateError):
        return "update_protocol_verification_failed"
    if isinstance(exc, (OSError, urllib.error.URLError)):
        return "network_or_ca_file_failed"
    return "https_check_failed"


def failure_details(exc):
    """Only fixed labels; never URLs, bodies, paths or headers."""
    stage = getattr(exc, "https_check_stage", "unknown")
    result = {"failure": failure_category(exc),
              "stage": stage if isinstance(stage, str) and stage in FAILURE_STAGES else "unknown"}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--https-check", action="store_true")
    parser.add_argument("--platform", choices=PLATFORMS)
    parser.add_argument("--channel", choices=("stable", "experimental"), default="stable")
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = check(args.platform, args.channel)
    except Exception as exc:
        report = {"schema": REPORT_SCHEMA, "success": False, "frozen": bool(getattr(sys, "frozen", False)),
                  **failure_details(exc)}
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
