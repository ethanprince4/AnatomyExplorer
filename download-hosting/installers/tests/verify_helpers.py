#!/usr/bin/env python3
"""Exercise the real helper transport with tiny fixture payloads and a local HTTP server.

Windows tests compile a console entry point, bypassing all UI/install code. Mac tests execute only the
download functions in Git Bash; native AppleScript, code signing, mount, copy and launch require macOS.
"""
from contextlib import contextmanager
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import sys

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_helpers", HERE / "build_helpers.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
PAYLOAD = bytes((i * 17 + 11) % 251 for i in range(329))
SIZES = (128, 128, 73)
HASH = hashlib.sha256(PAYLOAD).hexdigest()
PREFIX = b"previous-verified-original-part\x00\x01"


@contextmanager
def server(mode="ok", fault=0, gh_mode="ok"):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass

        def do_GET(self):
            range_header = self.headers.get("Range")
            requests.append((self.path, range_header))
            mirror = self.path.startswith("/r2/")
            if mirror:
                index = int(self.path.split("/")[-1])
                start = sum(SIZES[:index])
                data = PAYLOAD[start:start + SIZES[index]]
            else:
                index = -1
                data = PAYLOAD
            offset = int(range_header.split("=")[1].split("-")[0]) if range_header else 0
            active = mode if mirror and index == fault else gh_mode if not mirror else "ok"
            if active == "timeout":
                time.sleep(2.5)
                self.close_connection = True
                return
            if active == "missing":
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if active == "ignore-range":
                offset = 0
                range_header = None
            whole = len(data)
            data = data[offset:]
            if active == "corrupt":
                data = bytes([data[0] ^ 255]) + data[1:]
            self.send_response(206 if range_header else 200)
            if range_header:
                self.send_header("Content-Range", f"bytes {offset + (1 if active == 'bad-range' else 0)}-{whole - 1}/{whole}")
            self.send_header("Content-Length", str(len(data) + (3 if active == "oversize" else 0)))
            self.end_headers()
            try:
                self.wfile.write(data[:7] if active == "truncate" else data)
                self.wfile.flush()
                if active in ("truncate", "oversize"):
                    self.close_connection = True
                    self.connection.shutdown(socket.SHUT_WR)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    class QuietTestServer(ThreadingHTTPServer):
        def handle_error(self, request, address):
            # A rejected body or timed out fixture deliberately closes its connection.
            if not isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError)):
                super().handle_error(request, address)

    http = QuietTestServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{http.server_port}", requests
    finally:
        http.shutdown()
        http.server_close()
        thread.join()


def windows_tests(out, inputs):
    exe = out / "TransportHarness.exe"
    builder.run(builder.CSC, "/nologo", "/target:exe", "/optimize+", "/main:TransportHarness", f"/out:{exe}",
                "/r:System.dll", "/r:System.Drawing.dll", "/r:System.Windows.Forms.dll",
                HERE / "windows_installer/Installer.cs", HERE / "windows_installer/FragmentDownloader.cs",
                HERE / "tests/TransportHarness.cs", inputs / "Release.cs")
    results = []

    def case(name, have=0, mode="ok", fault=0, gh_mode="ok", bad_prefix=False, expect_failure=False):
        target = out / (name + ".bin")
        initial = PAYLOAD[:have]
        if bad_prefix:
            initial = bytes([initial[0] ^ 255]) + initial[1:]
        target.write_bytes(PREFIX + initial)
        with server(mode, fault, gh_mode) as (base, requests):
            result = subprocess.run([str(exe), base, str(target), str(len(PREFIX)), str(len(PAYLOAD)), HASH,
                                     ",".join(map(str, SIZES))], capture_output=True, text=True, timeout=15)
        actual = target.read_bytes()
        assert actual[:len(PREFIX)] == PREFIX, (name, "previous part was modified")
        assert len(actual) <= len(PREFIX) + len(PAYLOAD), (name, "appended beyond logical part")
        if expect_failure:
            assert result.returncode != 0, (name, result.stdout, result.stderr)
        else:
            assert result.returncode == 0, (name, result.stdout, result.stderr, requests)
            assert actual == PREFIX + PAYLOAD, (name, "wrong final bytes")
        results.append({"name": name, "requests": requests, "expected_failure": expect_failure})
        return requests

    assert all(p.startswith("/r2/") for p, _ in case("r2_success"))
    for have in (1, 127, 128, 129, 255, 256, 328):
        requests = case(f"resume_{have}", have)
        index = next(i for i in range(len(SIZES)) if have < sum(SIZES[:i+1]))
        local = have - sum(SIZES[:index])
        assert requests[0] == (f"/r2/{index}", f"bytes={local}-" if local else None)
        assert all(p.startswith("/r2/") for p, _ in requests)
    assert case("already_complete", len(PAYLOAD)) == []
    assert case("bad_saved_part", len(PAYLOAD), bad_prefix=True) == [("/gh/part.bin", None)]
    for mode in ("timeout", "truncate", "oversize", "missing"):
        requests = case("mirror_" + mode, have=128, mode=mode, fault=1)
        expected = 135 if mode == "truncate" else 128
        assert ("/gh/part.bin", f"bytes={expected}-") in requests, (mode, requests)
    for mode in ("bad-range", "ignore-range"):
        requests = case("mirror_" + mode, have=129, mode=mode, fault=1)
        assert ("/gh/part.bin", "bytes=129-") in requests
    requests = case("mirror_corrupt", mode="corrupt", fault=1)
    assert requests[-1] == ("/gh/part.bin", None), requests
    requests = case("gh_ignores_range", have=129, mode="missing", fault=1, gh_mode="ignore-range")
    assert requests[-2:] == [("/gh/part.bin", "bytes=129-"), ("/gh/part.bin", None)], requests
    case("gh_bad_range_rejected", have=129, mode="missing", fault=1, gh_mode="bad-range", expect_failure=True)
    case("both_sources_corrupt_rejected", mode="corrupt", fault=1, gh_mode="corrupt", expect_failure=True)
    requests = case("bad_saved_prefix", have=129, bad_prefix=True)
    assert requests[-1] == ("/gh/part.bin", None), requests

    # Also enter the public helper's real Main with a tiny fixture release: no Form may be created here.
    with server() as (base, requests):
        fragments = ",\n".join(f'new Fragment("{base}/r2/{i}", {sum(SIZES[:i])}L, {size}L)'
                               for i, size in enumerate(SIZES))
        release = builder.fill(HERE / "windows_installer/Release.cs.in", {
            "APP": "Helper transport fixture", "VERSION": "test", "TAG": "test", "NUMBER": "0.0.0.0",
            "BASE": base + "/gh", "PAGE": base, "SETUP": "fixture.bin",
            "PARTS": f'new Part("part.bin", {len(PAYLOAD)}L, "{HASH}", {fragments}),',
        })
        fixture_release = out / "FixtureRelease.cs"
        fixture_release.write_text(release, encoding="utf-8")
        fixture_exe = out / "PublicEntryFixture.exe"
        builder.run(builder.CSC, "/nologo", "/target:exe", "/optimize+", "/main:Program", f"/out:{fixture_exe}",
                    "/r:System.dll", "/r:System.Drawing.dll", "/r:System.Windows.Forms.dll",
                    HERE / "windows_installer/Installer.cs", HERE / "windows_installer/FragmentDownloader.cs", fixture_release)
        work = out / "public-entry"
        status = out / "public-entry-status.txt"
        result = subprocess.run([str(fixture_exe), "--headless-download", "--work", str(work), "--status", str(status)],
                                capture_output=True, text=True, timeout=15)
    assert result.returncode == 0 and status.read_text() == "downloaded", (result.stdout, result.stderr)
    assert (work / "test/fixture.bin").read_bytes() == PAYLOAD
    assert all(p.startswith("/r2/") for p, _ in requests), requests
    results.append({"name": "public_windows_headless_entry", "requests": requests})
    return results


def bash_path(path):
    return path.resolve().as_posix()


def mac_tests(out, mac_inputs):
    bash = Path("/bin/bash") if sys.platform == "darwin" else Path(r"C:\Program Files\Git\bin\bash.exe")
    if not bash.is_file():
        raise RuntimeError("Git Bash is required for local shell transport verification")
    results = []
    template = HERE / "mac_installer/install.sh.in"
    subprocess.run([str(bash), "-n", str(template)], check=True)
    subprocess.run([str(bash), "-n", str(mac_inputs / "install.sh")], check=True)
    # Test the real shell functions, excluding every native installation function and the dispatcher.
    full_fixture = builder.fill(template, {
        "BASE": "BASE_PLACEHOLDER", "MIRROR": "MIRROR_PLACEHOLDER", "DMG": "test.dmg", "BUNDLE": "test.app",
        "TOTAL": len(PAYLOAD), "BUNDLEBYTES": 1, "PARTS": f"  'part.bin {HASH} {len(PAYLOAD)}'",
        "FRAGMENTS": "\n".join(f"  'part.bin {i} {size}'" for i, size in enumerate(SIZES)),
    })
    fixture = full_fixture.split("\nrun_install() {", 1)[0]
    # Transport timeout limits are reduced only in the test wrapper; the production command is untouched.
    wrapper = '''
curl() {
  local args=() item
  while [ "$#" -gt 0 ]; do
    item="$1"; shift
    case "$item" in
      --speed-time) shift; args+=(--speed-time 1) ;;
      --retry) shift; args+=(--retry 0) ;;
      *) args+=("$item") ;;
    esac
  done
  command curl "${args[@]}"
}
'''
    if sys.platform != "darwin":
        wrapper = 'shasum() { shift 2; command sha256sum "$@"; }\n' + wrapper
    for mode in ("ok", "truncate", "timeout", "oversize", "corrupt", "missing"):
        work = out / ("mac_" + mode)
        work.mkdir()
        with server(mode, 1) as (base, requests):
            script = fixture.replace("BASE_PLACEHOLDER", base + "/gh").replace("MIRROR_PLACEHOLDER", base + "/r2")
            script += wrapper + f'\nWORK="{bash_path(work)}"\ndownload_parts\n'
            path = out / ("mac_" + mode + ".sh")
            path.write_text(script, encoding="utf-8", newline="\n")
            proc = subprocess.run([str(bash), str(path)], capture_output=True, text=True, timeout=15)
        assert proc.returncode == 0, (mode, proc.stdout, proc.stderr, requests)
        assert (work / "part.bin").read_bytes() == PAYLOAD, mode
        assert not list(work.glob("*.fragment.tmp")), mode
        if mode == "ok":
            assert all(p.startswith("/r2/") for p, _ in requests), requests
        else:
            assert requests[-1] == ("/gh/part.bin", None), requests
        results.append({"name": "mac_" + mode, "requests": requests})
    with server("corrupt", 1, "corrupt") as (base, requests):
        work = out / "mac_both_corrupt"
        work.mkdir()
        script = fixture.replace("BASE_PLACEHOLDER", base + "/gh").replace("MIRROR_PLACEHOLDER", base + "/r2")
        script += wrapper + f'\nWORK="{bash_path(work)}"\ndownload_parts\n'
        path = out / "mac_both_corrupt.sh"
        path.write_text(script, encoding="utf-8", newline="\n")
        proc = subprocess.run([str(bash), str(path)], capture_output=True, text=True, timeout=15)
    assert proc.returncode != 0 and "checksum" in (work / "status").read_text(), (proc.stdout, proc.stderr)
    results.append({"name": "mac_both_sources_corrupt_rejected", "requests": requests, "expected_failure": True})
    with server() as (base, requests):
        work = out / "mac_public_download_only"
        script = full_fixture.replace("BASE_PLACEHOLDER", base + "/gh").replace("MIRROR_PLACEHOLDER", base + "/r2")
        script = script.replace('case "${1:-}" in', wrapper + '\ncase "${1:-}" in')
        path = out / "mac_public_download_only.sh"
        path.write_text(script, encoding="utf-8", newline="\n")
        proc = subprocess.run([str(bash), str(path), "download-only", bash_path(work)],
                              capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert (work / "test.dmg").read_bytes() == PAYLOAD
    assert (work / "status").read_text().startswith("done|100|Downloaded and verified")
    assert all(p.startswith("/r2/") for p, _ in requests), requests
    results.append({"name": "public_mac_download_only_entry", "requests": requests})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("all", "windows", "mac"), default="all")
    parser.add_argument("--report", type=Path, default=HERE / "out/transport-verification.json")
    args = parser.parse_args()
    builder.load_plan()
    # Do not run the public helper EXE: its Main opens a window. Use the separate console harness.
    with tempfile.TemporaryDirectory(prefix="lh-helper-transport-") as temp:
        out = Path(temp)
        inputs, mac_inputs = builder.prepare(out / "prepared")
        results = []
        if args.platform in ("windows", "all"):
            results += windows_tests(out, inputs)
        if args.platform in ("mac", "all"):
            results += mac_tests(out, mac_inputs)
    record = {"fixture_bytes": len(PAYLOAD), "test_count": len(results), "passed": True,
              "native_windows_ui_or_installation_tested": False, "native_mac_build_or_installation_tested": False,
              "cases": results}
    dest = args.report
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: {len(results)} transport cases; report: {dest}")


if __name__ == "__main__":
    main()
