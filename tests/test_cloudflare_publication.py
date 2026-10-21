"""A mutable channel is written only after a complete immutable feed verifies."""
import contextlib
import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging"))
import cloudflare_updates as c
from update_payload import create_payload
from app import updater as u


class MemoryRemote:
    def __init__(self):
        self.objects = {}
        self.calls = []
        self.fail = None

    def probe(self, item, full=False, require_no_store=False):
        self.calls.append(("verify", item["key"], full))
        if self.fail == item["key"]:
            raise c.PublicationError("Public verification failed")
        stored = self.objects.get(item["key"])
        if stored is None:
            return False
        raw, cache = stored
        if len(raw) != item["size"] or u.sha(raw) != item["sha256"]:
            raise c.PublicationError("Existing public object hash differs; refusing overwrite")
        if require_no_store and cache != c.CHANNEL_CACHE:
            raise c.PublicationError("Cache-Control must be no-store")
        return True

    def put(self, item, path, cache_control):
        self.calls.append(("put", item["key"], cache_control))
        self.objects[item["key"]] = (path.read_bytes(), cache_control)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.feed, self.output = self.root / "feed", self.root / "stage"
        self.manifests = {}
        for platform in c.PLATFORMS:
            bundle = self.root / platform
            executable, version = (("Contents/MacOS/AnatomyExplorer", "Contents/Resources/VERSION")
                                   if platform == "macos-arm64" else ("AnatomyExplorer.exe", "_internal/VERSION"))
            for name, raw in ((executable, b"executable: " + platform.encode()), (version, b"4.0.12")):
                path = bundle / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            with contextlib.redirect_stdout(io.StringIO()):
                self.manifests[platform] = create_payload(bundle, self.feed, "4.0.12", platform)

    def stage(self):
        return c.stage_feed(self.feed, self.output)

    def alter_manifest(self, platform, callback):
        data = copy.deepcopy(self.manifests[platform])
        callback(data)
        (self.feed / u.manifest_names(platform)[0]).write_bytes(c.canonical_json(data))

    def make_reused(self):
        known, content = {}, {}
        for path in self.feed.glob("*.bin"):
            raw = path.read_bytes()
            known[path.name] = {"sha256": u.sha(raw), "size": len(raw)}
            content["updates/packs/" + u.sha(raw) + ".bin"] = (raw, c.IMMUTABLE_CACHE)
            path.unlink()
        return known, content

    def test_deterministic_hash_addressed_tree_is_consumed_by_both_clients(self):
        plan = self.stage()
        before = (self.output / c.PLAN_NAME).read_bytes()
        self.assertEqual(c.stage_feed(self.feed, self.output), plan)
        self.assertEqual((self.output / c.PLAN_NAME).read_bytes(), before)
        self.assertEqual(c.validate_stage(self.output), plan)
        for item in plan["immutable_objects"]:
            path = self.output / item["path"]
            self.assertEqual(item["size"], path.stat().st_size)
            self.assertEqual(item["sha256"], u.file_sha(path))
            self.assertIn(item["sha256"], item["key"])
        for platform in c.PLATFORMS:
            source = u.CloudflareSource(platform=platform)
            def read(url, limit, headers=None, expected_range=None):
                self.assertTrue(url.startswith(c.CLOUDFLARE_ORIGIN + "/"))
                raw = (self.output / "objects" / url.removeprefix(c.CLOUDFLARE_ORIGIN + "/")).read_bytes()
                self.assertLessEqual(len(raw), limit)
                return raw
            with patch.object(source, "read", side_effect=read):
                self.assertEqual(source.latest(), self.manifests[platform])

    def test_missing_pack_is_rejected_before_channel_is_staged(self):
        next(self.feed.glob("*.bin")).unlink()
        with self.assertRaisesRegex(c.PublicationError, "Missing local or known pack"):
            self.stage()
        self.assertFalse((self.output / "objects/updates/channels/stable.json").exists())

    def test_actual_pack_size_and_known_hash_must_match(self):
        path = next(self.feed.glob("*.bin"))
        raw = path.read_bytes()
        known = {path.name: {"sha256": "0" * 64, "size": len(raw)}}
        with self.assertRaisesRegex(c.PublicationError, "differs from known"):
            c.stage_feed(self.feed, self.output, known)
        path.write_bytes(raw + b"unexpected")
        with self.assertRaisesRegex(c.PublicationError, "size differs"):
            self.stage()

    def test_reused_pack_requires_matching_manifest_size(self):
        known, unused = self.make_reused()
        next(iter(known.values()))["size"] += 1
        with self.assertRaisesRegex(c.PublicationError, "Known pack size differs"):
            c.stage_feed(self.feed, self.output, known)

    def test_platforms_must_have_matching_release_identity(self):
        self.alter_manifest("macos-arm64", lambda data: data.update(version="4.0.13", release_tag="v4.0.13"))
        with self.assertRaisesRegex(c.PublicationError, "Both platform"):
            self.stage()

    def test_incomplete_protocol_manifest_is_rejected(self):
        self.alter_manifest("windows-x64", lambda data: data.update(files=data["files"][1:]))
        with self.assertRaisesRegex(c.PublicationError, "complete protocol-1"):
            self.stage()

    def test_local_tampering_and_omitted_pack_prevent_any_upload(self):
        plan = self.stage()
        remote = MemoryRemote()
        pack = next(item for item in plan["immutable_objects"] if item["key"].endswith(".bin"))
        path = self.output / pack["path"]
        raw = path.read_bytes()
        path.write_bytes(b"x" * len(raw))
        with self.assertRaisesRegex(c.PublicationError, "Staged object hash"):
            c.publish_stage(self.output, remote, remote)
        self.assertEqual(remote.calls, [])
        path.write_bytes(raw)
        plan["immutable_objects"].remove(pack)
        (self.output / c.PLAN_NAME).write_bytes(c.canonical_json(plan))
        with self.assertRaisesRegex(c.PublicationError, "Pack missing"):
            c.publish_stage(self.output, remote, remote)
        self.assertEqual(remote.calls, [])

    def test_missing_reused_public_pack_prevents_all_uploads(self):
        known, unused = self.make_reused()
        c.stage_feed(self.feed, self.output, known)
        remote = MemoryRemote()
        with self.assertRaisesRegex(c.PublicationError, "Reused pack is not public"):
            c.publish_stage(self.output, remote, remote)
        self.assertFalse(any(call[0] == "put" for call in remote.calls))

    def test_reused_packs_are_never_uploaded_and_channel_is_last(self):
        known, content = self.make_reused()
        plan = c.stage_feed(self.feed, self.output, known)
        remote = MemoryRemote()
        remote.objects.update(content)
        with contextlib.redirect_stdout(io.StringIO()):
            c.publish_stage(self.output, remote, remote)
        puts = [call for call in remote.calls if call[0] == "put"]
        self.assertEqual(next(i for i, call in enumerate(remote.calls) if call[0] == "put"),
                         len(plan["immutable_objects"]))
        self.assertEqual(puts[-1][1:], (plan["channel_object"]["key"], c.CHANNEL_CACHE))
        self.assertTrue(all(not call[1].endswith(".bin") for call in puts))
        self.assertEqual(remote.calls[-1], ("verify", plan["channel_object"]["key"], True))
        self.assertEqual(len(puts), 5)
        for item in plan["immutable_objects"]:
            if item["key"].endswith(".bin"):
                self.assertNotIn("path", item)

    def test_public_verification_failure_prevents_channel_publication(self):
        plan = self.stage()
        remote = MemoryRemote()
        first = plan["immutable_objects"][0]
        original_put = remote.put
        def fail_after_put(item, path, cache):
            original_put(item, path, cache)
            remote.fail = item["key"]
        remote.put = fail_after_put
        with self.assertRaisesRegex(c.PublicationError, "Public verification failed"):
            c.publish_stage(self.output, remote, remote)
        self.assertEqual([call[1] for call in remote.calls if call[0] == "put"], [first["key"]])
        self.assertNotIn(plan["channel_object"]["key"], remote.objects)

    def test_conflicting_immutable_object_is_never_overwritten(self):
        plan = self.stage()
        remote = MemoryRemote()
        item = plan["immutable_objects"][0]
        remote.objects[item["key"]] = (b"x" * item["size"], c.IMMUTABLE_CACHE)
        with self.assertRaisesRegex(c.PublicationError, "refusing overwrite"):
            c.publish_stage(self.output, remote, remote)
        self.assertFalse(any(call[0] == "put" for call in remote.calls))

    def test_rerun_only_writes_channel_and_full_verifies_local_new_packs(self):
        plan, remote = self.stage(), MemoryRemote()
        with contextlib.redirect_stdout(io.StringIO()):
            c.publish_stage(self.output, remote, remote)
            remote.calls.clear()
            c.publish_stage(self.output, remote, remote)
        self.assertEqual([call[1] for call in remote.calls if call[0] == "put"], [plan["channel_object"]["key"]])
        for call in remote.calls:
            if call[0] == "verify":
                self.assertTrue(call[2])

    def test_explicit_empty_channel(self):
        plan = c.stage_empty(self.output, "experimental")
        self.assertEqual(plan["immutable_objects"], [])
        raw = (self.output / plan["channel_object"]["path"]).read_bytes()
        self.assertEqual(json.loads(raw), {"schema": 1, "channel": "experimental", "platforms": {}})
        remote = MemoryRemote()
        with contextlib.redirect_stdout(io.StringIO()):
            c.publish_stage(self.output, remote, remote)
        self.assertEqual([call[0] for call in remote.calls], ["put", "verify"])

    def test_wrangler_uses_existing_cli_remote_and_cache_headers_without_shell(self):
        plan = self.stage()
        wrangler = self.root / "wrangler.js"
        wrangler.write_text("// test fixture")
        item = plan["channel_object"]
        uploader = c.WranglerUploader(wrangler)
        with patch.object(c.subprocess, "run") as run:
            run.return_value.returncode = 0
            uploader.put(item, self.output / item["path"], c.CHANNEL_CACHE)
        args, kwargs = run.call_args
        self.assertEqual(args[0][:5], ["node", str(wrangler), "r2", "object", "put"])
        self.assertIn("--remote", args[0])
        self.assertEqual(args[0][-2:], ["--cache-control", "no-store"])
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["encoding"], "utf-8")
        self.assertEqual(kwargs["errors"], "replace")
        self.assertEqual(kwargs["env"]["WRANGLER_WRITE_LOGS"], "false")


class FakeResponse(io.BytesIO):
    def __init__(self, raw, url, status=200, headers=None):
        super().__init__(raw)
        self.url, self.status, self.headers = url, status, headers or {}


class PublicVerificationTests(unittest.TestCase):
    def test_head_range_and_full_hash_are_checked_without_trusting_etag(self):
        raw = b"pack bytes"
        item = {"key": "updates/packs/" + u.sha(raw) + ".bin", "size": len(raw), "sha256": u.sha(raw)}
        store = c.PublicObjects()
        calls = []
        def opened(request, timeout):
            calls.append(request)
            if request.method == "HEAD":
                return FakeResponse(b"", request.full_url, headers={"Content-Length": str(len(raw))})
            if request.get_header("Range"):
                return FakeResponse(raw[:1], request.full_url, 206,
                                    {"Content-Length": "1", "Content-Range": f"bytes 0-0/{len(raw)}"})
            return FakeResponse(raw, request.full_url)
        with patch.object(store.opener, "open", side_effect=opened):
            self.assertTrue(store.probe(item))
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(request.get_header("Accept-encoding") == "identity" for request in calls))

    def test_server_ignoring_range_is_rejected(self):
        raw = b"pack bytes"
        item = {"key": "updates/packs/" + u.sha(raw) + ".bin", "size": len(raw), "sha256": u.sha(raw)}
        store = c.PublicObjects()
        def opened(request, timeout):
            return FakeResponse(raw, request.full_url, headers={"Content-Length": str(len(raw))})
        with patch.object(store.opener, "open", side_effect=opened):
            with self.assertRaisesRegex(c.PublicationError, "exact ranges"):
                store.probe(item)

    def test_wrong_hash_and_channel_cache_policy_are_rejected(self):
        raw = b'{"schema":1}'
        item = {"key": "updates/channels/stable.json", "size": len(raw), "sha256": "0" * 64}
        store = c.PublicObjects()
        def opened(request, timeout):
            return FakeResponse(raw, request.full_url, headers={"Content-Length": str(len(raw)), "Cache-Control": "public"})
        with patch.object(store.opener, "open", side_effect=opened):
            with self.assertRaisesRegex(c.PublicationError, "no-store"):
                store.probe(item, require_no_store=True)
            with self.assertRaisesRegex(c.PublicationError, "hash differs"):
                store.probe(item)


if __name__ == "__main__":
    unittest.main()
