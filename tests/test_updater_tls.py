"""Updater TLS verification with isolated loopback servers and a public test key.

The key below is a disposable fixture, never a credential or production CA.
No certificates are installed into operating-system or application trust stores.
"""
import gzip
import json
import os
import runpy
import ssl
import sys
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

import certifi

from app import https_check, tls, updater as u
from tests.fixture_paths import fixture_root

TEST_CERTIFICATE = """-----BEGIN CERTIFICATE-----
MIIDHjCCAgagAwIBAgIBAjANBgkqhkiG9w0BAQsFADAUMRIwEAYDVQQDDAlsb2Nh
bGhvc3QwIBcNMjAwMTAxMDAwMDAwWhgPMjEyNjAxMDEwMDAwMDBaMBQxEjAQBgNV
BAMMCWxvY2FsaG9zdDCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBALEQ
WLOda0M1M0eh3mv9VQpfl8f2F5sdFkQzdN1fQcgNeP26x7jKVG1GpksRwYWCoJP1
O7I93lIBGiAzShNVsG33YQJnVjUB+ZEfOm9ji+sTFCewLhssfoAmNS1esEsRMU41
kyQ6co6GyGWQ3qs8eM26L4eJ8/YSf3nOweLV2NhizBVCokdDOov7Zx6/bRXHpFse
VXjOXgW/e9EQSpb+HZ+bj8nfgvghDU962xTS9i2GZpweUgARH+JffbTpqvCIA1bo
zj6lPMuLvp2TJka04WfG5v41fBh8kpr3DRb6xbBOADTWKD5xQWVIqrRbCWLD63uy
DhRDsBvH+ogyNpYfIVkCAwEAAaN5MHcwDwYDVR0TAQH/BAUwAwEB/zAOBgNVHQ8B
Af8EBAMCAYYwFAYDVR0RBA0wC4IJbG9jYWxob3N0MB0GA1UdDgQWBBQK4m8qs2f7
rJhrDNTYsVfLZJQwGjAfBgNVHSMEGDAWgBQK4m8qs2f7rJhrDNTYsVfLZJQwGjAN
BgkqhkiG9w0BAQsFAAOCAQEADuCbV0F6jP7dm+I2yjhHOJGAERXuK2hCYXaxqBM1
hrTGX8QZqRhfz6Cj6wjuqpJ/J1ChG1U7ASPAZfnh2bJSDyd3nb2XWwf0imCHV//5
mVlUxozEicYHsLcy3ATfjuU+W12kPhcSxiaZdHC3xSK/uZEXU4d3VqZXbk5bggX3
x1g3oUDBE6tsgQyMED9r6RVtVzY4T5ngIlufIgtJudGDByb8nisA8pJzhdRMQMf2
Rdd5jsxolu/E9UwH6DjZteFvY3ga0OEwthfTlWC9GdOBrk7Ckib3sXx0/oQURVIT
G5glwN+3JZgydUn+cMAoLZRLP6pAgD706kWFzCggMHiSDw==
-----END CERTIFICATE-----
"""
TEST_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQCxEFiznWtDNTNH
od5r/VUKX5fH9hebHRZEM3TdX0HIDXj9use4ylRtRqZLEcGFgqCT9TuyPd5SARog
M0oTVbBt92ECZ1Y1AfmRHzpvY4vrExQnsC4bLH6AJjUtXrBLETFONZMkOnKOhshl
kN6rPHjNui+HifP2En95zsHi1djYYswVQqJHQzqL+2cev20Vx6RbHlV4zl4Fv3vR
EEqW/h2fm4/J34L4IQ1PetsU0vYthmacHlIAER/iX3206arwiANW6M4+pTzLi76d
kyZGtOFnxub+NXwYfJKa9w0W+sWwTgA01ig+cUFlSKq0Wwliw+t7sg4UQ7Abx/qI
MjaWHyFZAgMBAAECggEADnqGtlFGBx3fjpj25h+2B34fnDNMZNuxCWynvr5eU6x+
W0kdscehtbnUOUk/aNpwpQillAKpHk2GxGFNSl10atmSri6jBvydWreSAK/ELjnG
KSSn8ILn6TS2nnoislC6lmmdGZZJ7cupsVxySNBOFIyH/G5Ua6fBksVMZ28TJ0Zy
EHtoPmmWE9GUknpKCqC6jWUMeANTY2H/u7bO1I9M029c8b4Vg/GXLEQ2tl/SKVuz
DNKX7ZZIH+eVmXn1CByVyUQdWZ+JHg5iQT0sln047nvum3ueHclkRbUsLSBY/6XT
XuXj5tKQ2y181u3Qzygw2Cdg7MAzoeyi+4VnfHhTDQKBgQDcjQflT/wGpn9vlpuA
slxkDFtN8gDHwanBL9XffNw3wr1t7mTG90ZQ9wlCiV/UMTI00OPaW3E7k/kZIFZo
FmwA5VuB5MAjWKXrhVZgHDXBKcjWHPKa+VE9lToimm0/irLUwxFS2On7Uk4PJcyo
HTmKcmpRUQ7H+AAXmjqsS8z+BwKBgQDNhfYzff959LEFVado4Zc9JiDneEpwWbTM
RUrrurqyMCt0NTz0j9NHLBg4EZxI9R9LIoV6c+/TMhYRN/hdvkcaYiy5tZ51tl96
7dhGKH/SiMJZU82fd2Bap4/TlyLAeXN4zCMwaZEIv+PqgD3aIZ4Pba6tnPwKxF78
3HbxViENnwKBgES0qoEFKb3ooEpi4I53AdEpCEh/2z5fVkKYZEf63Z+BSwG0AjD5
Vy5hxsCziubPbJSHfnPHiL7GmhL5v/EtCvg8ewU7/Z8FPqrgHshSAWzrV2VcHzen
82b71eBxuxbQXmVpXzwv1rQ0L50IaXj1obc/bV9noPMqjtzLbvu9oV6BAoGBAJp0
JoakFi8s+SwtJtbnUqWd1fSerjKo9/rbyGZHuq7XDJEUwW55+CnwtXLNqUobDR2G
IBHat01cwsDF811f9keZqEsYdrG4ESFtRa/UF9u883H2TP2e1UbLzocRegh0PZd2
sqtbaqfMrhg5sEISKZsmrrPC2pes5EXb2XedZtG5AoGBANlQH+AoqaeURst22/Mc
pv648g2XFOVDQrRBHLlVOBOjDKehMHktpArpuWkGH7hhFBjUWKRSFCLwbYuY8Dt8
hjtzpQuOb5nRgDiS6gOlepTf9oMBPTRm40Cy5PoMM+kXbPZ3MjABXORXuqEUhdhr
xpyZ2r/9kuQd8OStOK9O2rOU
-----END PRIVATE KEY-----
"""


class TLSVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="AnatomyExplorer-tls-test-")
        cls.root = fixture_root(cls.temp.name)
        cls.ca = cls.root / "public-test-ca.pem"
        cls.key = cls.root / "public-test-key.pem"
        cls.ca.write_text(TEST_CERTIFICATE, encoding="ascii")
        cls.key.write_text(TEST_PRIVATE_KEY, encoding="ascii")

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith("/redirect"):
                    locations = {
                        "/redirect-ok": "/ok",
                        "/redirect-outside": "https://untrusted.invalid/",
                        "/redirect-downgrade": f"http://localhost:{self.server.server_port}/ok",
                        "/redirect-wrong-host": f"https://127.0.0.1:{self.server.server_port}/ok",
                    }
                    self.send_response(302)
                    self.send_header("Location", locations[self.path])
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.send_header("Content-Length", "8")
                    self.end_headers()
                    self.wfile.write(b"verified")

            def log_message(self, *args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cls.ca, cls.key)
        cls.server.socket = context.wrap_socket(cls.server.socket, server_side=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.temp.cleanup()

    def setUp(self):
        original_trusted_url = u.trusted_url

        def fixture_url(url):
            parsed = urlsplit(url)
            if (parsed.scheme == "https" and parsed.hostname in {"localhost", "127.0.0.1"}
                    and parsed.port == self.server.server_port and not parsed.username and not parsed.password):
                return url
            return original_trusted_url(url)

        # Scope just this test server into URL validation; production host policy
        # remains in force for every redirect outside the isolated fixture.
        self.addCleanup(patch.stopall)
        patch.object(u, "trusted_url", side_effect=fixture_url).start()
        patch.object(u.urllib.request, "getproxies", return_value={}).start()

    def source(self, trust_fixture=False):
        if trust_fixture:
            with patch.object(certifi, "where", return_value=str(self.ca)):
                return u.GitHubSource()
        return u.GitHubSource()

    def url(self, path="/ok", host="localhost"):
        return f"https://{host}:{self.server.server_port}{path}"

    def test_context_has_explicit_roots_and_keeps_verification(self):
        factory = ssl._create_default_https_context
        with patch.dict(os.environ, {"SSL_CERT_FILE": str(self.root / "missing.pem"),
                                     "SSL_CERT_DIR": str(self.root / "missing-dir")}):
            context = tls.https_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertGreaterEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertGreater(context.cert_store_stats()["x509_ca"], 10)
        self.assertNotIn(ssl.PEM_cert_to_DER_cert(TEST_CERTIFICATE), context.get_ca_certs(binary_form=True))
        self.assertIs(ssl._create_default_https_context, factory)

    def test_missing_packaged_ca_fails_closed(self):
        with patch.object(certifi, "where", return_value=str(self.root / "missing.pem")):
            with self.assertRaises(OSError):
                self.source()

    def test_untrusted_server_certificate_rejected(self):
        with self.assertRaises(urllib.error.URLError) as raised:
            self.source().read(self.url(), 8)
        self.assertIsInstance(raised.exception.reason, ssl.SSLCertVerificationError)

    def test_fixture_ca_is_trusted_only_by_explicit_test_context(self):
        self.assertEqual(self.source(trust_fixture=True).read(self.url(), 8), b"verified")
        with self.assertRaises(urllib.error.URLError) as raised:
            self.source().read(self.url(), 8)
        self.assertIsInstance(raised.exception.reason, ssl.SSLCertVerificationError)

    def test_trusted_certificate_wrong_hostname_rejected(self):
        with self.assertRaises(urllib.error.URLError) as raised:
            self.source(trust_fixture=True).read(self.url(host="127.0.0.1"), 8)
        self.assertIsInstance(raised.exception.reason, ssl.SSLCertVerificationError)
        self.assertEqual(raised.exception.reason.verify_code, 64)

    def test_trusted_redirect_keeps_verification(self):
        source = self.source(trust_fixture=True)
        self.assertEqual(source.read(self.url("/redirect-ok"), 8), b"verified")
        with self.assertRaises(urllib.error.URLError) as raised:
            source.read(self.url("/redirect-wrong-host"), 8)
        self.assertIsInstance(raised.exception.reason, ssl.SSLCertVerificationError)

    def test_untrusted_and_http_redirects_rejected(self):
        source = self.source(trust_fixture=True)
        for path in ("/redirect-outside", "/redirect-downgrade"):
            with self.subTest(path=path), self.assertRaisesRegex(u.UpdateError, "Untrusted"):
                source.read(self.url(path), 8)


class HTTPSDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="AnatomyExplorer-https-report-test-")
        self.root = fixture_root(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def payload(self):
        pack = "AnatomyExplorer-Windows-pack-0000.bin"
        contents = {"AnatomyExplorer.exe": b"test binary", "_internal/VERSION": b"3.1.1"}
        files, blobs, packed = [], {}, b""
        for name, data in contents.items():
            digest, raw = u.sha(data), gzip.compress(data, mtime=0)
            blobs[digest] = {"pack": pack, "offset": len(packed), "size": len(raw), "raw_size": len(data)}
            packed += raw
            files.append({"path": name, "size": len(data), "sha256": digest, "chunks": [digest]})
        manifest = {"schema": 1, "launcher": 1, "platform": "windows-x64", "version": "3.1.1",
                    "files": files, "blobs": blobs, "packs": {pack: len(packed)}}
        raw_manifest = json.dumps(manifest).encode()
        prefix = f"https://github.com/{u.REPO}/releases/download/v3.1.1/"
        assets = [
            {"name": u.MANIFEST, "size": len(raw_manifest), "digest": "sha256:" + u.sha(raw_manifest),
             "browser_download_url": prefix + u.MANIFEST},
            {"name": pack, "size": len(packed), "browser_download_url": prefix + pack},
            {"name": https_check.INSTALLERS["windows-x64"], "size": 1000,
             "browser_download_url": prefix + https_check.INSTALLERS["windows-x64"]},
        ]
        release = {"tag_name": "v3.1.1", "assets": assets, "draft": False, "prerelease": False}
        return manifest, raw_manifest, packed, release

    def test_diagnostic_uses_manifest_digest_real_chunk_and_bounded_installer_range(self):
        manifest, raw_manifest, packed, release = self.payload()
        reads = []

        def read(source, url, limit, headers=None, expected_range=None):
            reads.append((url, limit, headers, expected_range))
            if url == u.API:
                return json.dumps(release).encode()
            if url.endswith(u.MANIFEST):
                return raw_manifest
            if url.endswith(".bin"):
                value = min(manifest["blobs"].values(), key=lambda b: b["size"])
                self.assertEqual(headers, {"Range": f"bytes={value['offset']}-{value['offset'] + value['size'] - 1}"})
                self.assertEqual(limit, value["size"])
                self.assertEqual(expected_range, f"bytes {value['offset']}-{value['offset'] + value['size'] - 1}/{len(packed)}")
                return packed[value["offset"]:value["offset"] + value["size"]]
            self.assertEqual(headers, {"Range": "bytes=0-63"})
            self.assertEqual(limit, 64)
            self.assertEqual(expected_range, "bytes 0-63/1000")
            return b"i" * 64

        with patch.object(u.GitHubSource, "read", new=read):
            result = https_check.check("windows-x64")
        self.assertEqual(len(reads), 4)
        self.assertTrue(result["success"] and result["manifest"]["api_digest_verified"])
        self.assertTrue(result["chunk"]["integrity_verified"] and result["installer"]["range_verified"])
        self.assertEqual(result["installer"]["downloaded_bytes"], 64)

    def test_diagnostic_rejects_tampered_manifest_before_chunk_or_installer(self):
        manifest, raw, packed, release = self.payload()
        release["assets"][0]["digest"] = "sha256:" + "0" * 64
        with patch.object(u.GitHubSource, "read", side_effect=[json.dumps(release).encode(), raw]) as read:
            with self.assertRaisesRegex(u.UpdateError, "integrity"):
                https_check.check("windows-x64")
        self.assertEqual(read.call_count, 2)

    def test_failed_report_does_not_publish_urls_queries_credentials_or_local_paths(self):
        private = "https://name:password@release-assets.githubusercontent.com/a?secret=token C:/Users/private"
        exc = urllib.error.URLError(ssl.SSLCertVerificationError(1, private))
        path = self.root / "https.json"
        with patch.object(https_check, "check", side_effect=exc):
            self.assertEqual(https_check.main(["--report", str(path)]), 1)
        report = json.loads(path.read_text())
        self.assertEqual(report["failure"], "certificate_verification_failed")
        self.assertNotIn(private, json.dumps(report))
        self.assertEqual(report["stage"], "unknown")
        self.assertEqual(set(report), {"schema", "success", "frozen", "failure", "stage"})

    def test_http_failure_stage_is_preserved_without_private_details(self):
        from email.message import Message
        headers = Message()
        headers["X-RateLimit-Remaining"] = "0"
        private = "https://name:password@example.invalid/file?secret=token"
        for stage in https_check.FAILURE_STAGES:
            with self.subTest(stage=stage):
                error = urllib.error.HTTPError(private, 403, private, headers, None)
                def fail():
                    raise error
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    https_check.at_stage(stage, fail)
                self.assertIs(raised.exception, error)
                details = https_check.failure_details(error)
                self.assertEqual(details, {"failure": "http_403", "stage": stage,
                                           "rate_limit_exhausted": True})
                self.assertNotIn(private, json.dumps(details))
        error.https_check_stage = private
        self.assertEqual(https_check.failure_details(error)["stage"], "unknown")

    def test_http_403_without_rate_limit_header_is_not_called_rate_limit(self):
        error = urllib.error.HTTPError("https://example.invalid/", 403, "Forbidden", {}, None)
        error.https_check_stage = "manifest"
        self.assertEqual(https_check.failure_details(error),
                         {"failure": "http_403", "stage": "manifest", "rate_limit_exhausted": False})

    def test_launcher_diagnostic_exits_before_qt_settings_managed_store_and_ui(self):
        report = self.root / "https.json"
        launcher = Path(__file__).resolve().parents[1] / "packaging" / "launcher.py"
        with patch.object(sys, "argv", [str(launcher), "--https-check", "--report", str(report)]), \
                patch.object(sys, "dont_write_bytecode", True), \
                patch.dict(os.environ, {"AE_TEST_SETTINGS_DIR": str(self.root / "settings")}), \
                patch.object(https_check, "check", return_value={"success": True}), \
                patch.object(u, "launch_managed", side_effect=AssertionError("managed launch")), \
                patch.object(u, "store_for", side_effect=AssertionError("update store")), \
                patch.object(runpy, "run_module", side_effect=AssertionError("UI")):
            with self.assertRaises(SystemExit) as raised:
                runpy.run_path(str(launcher), run_name="__main__")
        self.assertEqual(raised.exception.code, 0)
        self.assertTrue(report.exists())
        self.assertFalse((self.root / "settings").exists())


if __name__ == "__main__":
    unittest.main()
