"""Bounded, read-only updater HTTPS check for source and packaged applications.

Only the fixed public stable feed is accessed. Reports contain no local paths,
proxy credentials, redirect query strings, update stores, or study information.
"""
import argparse
import json
import os
import ssl
import sys
import urllib.error
from pathlib import Path

import certifi

from . import updater as u
from .tls import https_context

INSTALLERS = {
    "windows-x64": "AnatomyExplorer-Setup-Windows.exe",
    "macos-arm64": "AnatomyExplorer-macOS-AppleSilicon.dmg",
}
INSTALLER_SAMPLE = 64
FAILURE_STAGES = frozenset({"tls_context", "release_api", "manifest", "chunk", "installer"})


def at_stage(stage, operation):
    """Preserve the original exception while retaining a safe request label."""
    try:
        return operation()
    except Exception as exc:
        exc.https_check_stage = stage
        raise


def check(platform=None):
    source = at_stage("tls_context", lambda: u.GitHubSource(platform=platform, channel="stable"))
    context = at_stage("tls_context", https_context)
    ca = Path(certifi.where())
    frozen = bool(getattr(sys, "frozen", False))
    bundled = frozen and ca.absolute().is_relative_to(Path(sys._MEIPASS).absolute())
    report = {
        "schema": 1,
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
    # Use the same API read, release binding, API digest and manifest validation
    # as latest(); retain metadata for the additional installer range check.
    # CI runners share anonymous API quotas. This optional, ephemeral credential
    # is used only by this diagnostic's API request, never asset downloads.
    token = os.environ.get("AE_HTTPS_CHECK_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else None
    release = at_stage("release_api", lambda: json.loads(source.read(u.API, 2 * 1024 * 1024, headers)))
    if not isinstance(release, dict):
        raise u.UpdateError("Invalid stable release metadata")
    manifest = at_stage("manifest", lambda: source.from_release(release))
    if manifest is None or not manifest["blobs"]:
        raise u.UpdateError("Stable release has no incremental update payload")
    tag = release["tag_name"]  # from_release has validated the numeric stable tag
    prefix = f"https://github.com/{u.REPO}/releases/download/{tag}/"
    name = u.MAC_MANIFEST if source.platform == "macos-arm64" else u.MANIFEST
    assets = {a["name"]: a for a in release.get("assets", [])}
    report["api"] = {"url": u.API, "published_stable": True, "release_tag": tag}
    report["manifest"] = {
        "url": prefix + name,
        "version": manifest["version"],
        "sha256": assets[name]["digest"][7:],
        "bytes": assets[name]["size"],
        "api_digest_verified": True,
    }

    # The smallest real blob is sufficient to exercise the GitHub -> CDN ranged
    # transport and bounded decompression without fetching whole packs/installers.
    digest, blob = min(manifest["blobs"].items(), key=lambda item: (item[1]["size"], item[0]))
    raw = at_stage("chunk", lambda: source.chunk(blob, manifest["packs"][blob["pack"]]))
    u.unpack_chunk(raw, blob["raw_size"], digest)
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

    installer_name = INSTALLERS[source.platform]
    installer = assets.get(installer_name, {})
    size = installer.get("size")
    url = prefix + installer_name
    if (installer.get("browser_download_url") != url or
            type(size) is not int or size < INSTALLER_SAMPLE):
        raise u.UpdateError("Missing or untrusted release installer")
    expected_range = f"bytes 0-{INSTALLER_SAMPLE - 1}/{size}"
    sample = at_stage("installer", lambda: source.read(
        url, INSTALLER_SAMPLE, {"Range": f"bytes=0-{INSTALLER_SAMPLE - 1}"}, expected_range))
    if len(sample) != INSTALLER_SAMPLE:
        raise u.UpdateError("Interrupted installer range check")
    report["installer"] = {
        "url": url,
        "size": size,
        "content_range": expected_range,
        "downloaded_bytes": len(sample),
        "range_verified": True,
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
    """Only fixed labels and a boolean; never URLs, bodies, paths or headers."""
    stage = getattr(exc, "https_check_stage", "unknown")
    result = {"failure": failure_category(exc),
              "stage": stage if isinstance(stage, str) and stage in FAILURE_STAGES else "unknown"}
    if isinstance(exc, urllib.error.HTTPError):
        result["rate_limit_exhausted"] = bool(
            exc.headers is not None and exc.headers.get("X-RateLimit-Remaining") == "0")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--https-check", action="store_true")
    parser.add_argument("--platform", choices=tuple(INSTALLERS))
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = check(args.platform)
    except Exception as exc:
        report = {"schema": 1, "success": False, "frozen": bool(getattr(sys, "frozen", False)),
                  **failure_details(exc)}
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
