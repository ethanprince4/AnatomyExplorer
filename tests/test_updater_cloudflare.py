"""Pinned Cloudflare transport, metadata binding and protocol-1 bridge lifecycle."""
import copy
import hashlib
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import updater as u
from tests.fixture_paths import fixture_root
from tests.test_updater import create_payload


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def content(value):
    return {"sha256": u.sha(value), "size": len(value)}


class Response(io.BytesIO):
    def __init__(self, data, url, status=200, headers=None):
        super().__init__(data)
        self.url, self.status, self.headers = url, status, headers or {}


class Feed:
    def __init__(self, manifest, packs, catalog_change=None, channel_change=None, raw_manifest=None):
        self.manifest = manifest
        self.raw_manifest = raw_manifest if raw_manifest is not None else encoded(manifest)
        self.packed = {name: (Path(packs) / name).read_bytes() for name in manifest["packs"]}
        catalog = {"schema": 1, "channel": u.manifest_channel(manifest), "platform": manifest["platform"],
                   "release_tag": manifest["release_tag"], "version": manifest["version"],
                   "manifest": content(self.raw_manifest), "packs": {name: content(data) for name, data in self.packed.items()}}
        if catalog_change:
            catalog_change(catalog)
        self.catalog = catalog
        self.raw_catalog = encoded(catalog)
        channel = {"schema": 1, "channel": u.manifest_channel(manifest), "release_tag": manifest["release_tag"],
                   "version": manifest["version"], "platforms": {manifest["platform"]: content(self.raw_catalog)}}
        if channel_change:
            channel_change(channel)
        self.channel = channel
        prefix = f"{u.CLOUDFLARE_ORIGIN}/updates/releases/{manifest['release_tag']}/{manifest['platform']}/"
        self.catalog_url = prefix + u.sha(self.raw_catalog) + ".json"
        self.manifest_url = prefix + u.sha(self.raw_manifest) + ".json"
        self.channel_url = f"{u.CLOUDFLARE_ORIGIN}/updates/channels/{u.manifest_channel(manifest)}.json"
        self.objects = {self.channel_url: encoded(channel), self.catalog_url: self.raw_catalog,
                        self.manifest_url: self.raw_manifest}
        self.objects.update({f"{u.CLOUDFLARE_ORIGIN}/updates/packs/{u.sha(data)}.bin": data
                             for data in self.packed.values()})
        self.requests = []

    def open(self, request, timeout):
        url = request.full_url
        self.requests.append((url, dict(request.header_items())))
        if url not in self.objects:
            raise AssertionError("Unexpected request: " + url)
        data = self.objects[url]
        byte_range = request.get_header("Range")
        if byte_range:
            start, end = map(int, byte_range.removeprefix("bytes=").split("-"))
            return Response(data[start:end+1], url, 206, {"Content-Range": f"bytes {start}-{end}/{len(data)}"})
        return Response(data, url)

    def source(self):
        source = u.CloudflareSource(self.manifest["platform"], u.manifest_channel(self.manifest))
        source.opener = self
        return source


class CloudflareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = fixture_root(self.temp.name)
        self.bundle = self.root / "bundle"
        (self.bundle / "_internal/data/anatomy").mkdir(parents=True)
        (self.bundle / "AnatomyExplorer.exe").write_bytes(b"test binary")
        (self.bundle / "_internal/VERSION").write_text("4.0.12")
        (self.bundle / "_internal/data/anatomy/model.bin").write_bytes(b"model bytes" * 500)
        self.packs = self.root / "packs"
        self.manifest = create_payload(self.bundle, self.packs, "4.0.12")

    def test_discovery_derives_all_urls_and_binds_manifest_packs(self):
        feed = Feed(self.manifest, self.packs)
        source = feed.source()
        self.assertEqual(source.latest(), self.manifest)
        self.assertEqual(source.channel_url, feed.channel_url)
        self.assertEqual(source.catalog_url, feed.catalog_url)
        self.assertEqual(source.manifest_url, feed.manifest_url)
        self.assertEqual(source.manifest_digest, u.sha(feed.raw_manifest))
        self.assertEqual(source.manifest_size, len(feed.raw_manifest))
        for digest, blob in self.manifest["blobs"].items():
            raw = source.chunk(blob, self.manifest["packs"][blob["pack"]])
            self.assertEqual(u.sha(u.unpack_chunk(raw, blob["raw_size"], digest)), digest)
        self.assertTrue(all(url.startswith(u.CLOUDFLARE_ORIGIN + "/updates/") for url, _ in feed.requests))
        self.assertTrue(all(headers["Accept-encoding"] == "identity" for _, headers in feed.requests))

    def test_empty_or_unsupported_platform_has_no_release(self):
        source = u.CloudflareSource("windows-x64")
        for value in ({"schema": 1, "channel": "stable", "platforms": {}},
                      {"schema": 1, "channel": "stable", "release_tag": "v4.0.12", "version": "4.0.12",
                       "platforms": {"macos-arm64": {"sha256": "1"*64, "size": 100}}}):
            with self.subTest(value=value), patch.object(source, "read", return_value=encoded(value)) as read:
                self.assertIsNone(source.latest())
                self.assertEqual(read.call_count, 1)
                self.assertEqual(source.urls, {})

    def test_channel_identity_shape_and_descriptor_rejections(self):
        invalid = [lambda c: c.update(schema=True), lambda c: c.update(channel="experimental"),
                   lambda c: c.update(release_tag="v4.0.13"), lambda c: c.update(version="4.90.1"),
                   lambda c: c.update(url="https://evil.invalid/catalog"),
                   lambda c: c["platforms"]["windows-x64"].update(url="https://evil.invalid/catalog"),
                   lambda c: c["platforms"]["windows-x64"].update(size=True),
                   lambda c: c["platforms"]["windows-x64"].update(size=u.MAX_CATALOG+1),
                   lambda c: c["platforms"]["windows-x64"].update(sha256="A"*64),
                   lambda c: c["platforms"].update(other={"sha256": "0"*64, "size": 1})]
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(u.UpdateError):
                Feed(self.manifest, self.packs, channel_change=change).source().latest()

    def test_catalog_identity_unknown_url_and_pack_membership_rejected(self):
        pack = next(iter(self.manifest["packs"]))
        invalid = [lambda c: c.update(schema=True), lambda c: c.update(channel="experimental"),
                   lambda c: c.update(platform="macos-arm64"), lambda c: c.update(release_tag="v4.0.13"),
                   lambda c: c.update(version="4.0.13"), lambda c: c.update(url="https://evil.invalid"),
                   lambda c: c["manifest"].update(url="https://evil.invalid"),
                   lambda c: c["packs"][pack].update(url="https://evil.invalid"),
                   lambda c: c["packs"].clear(),
                   lambda c: c["packs"][pack].update(size=c["packs"][pack]["size"]+1),
                   lambda c: c["packs"].update({"AnatomyExplorer-Windows-pack-9999.bin": {"sha256": "1"*64, "size": 1}})]
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(u.UpdateError):
                Feed(self.manifest, self.packs, catalog_change=change).source().latest()

    def test_catalog_and_manifest_byte_tampering_and_lengths_rejected(self):
        for target in ("catalog_url", "manifest_url"):
            for suffix in (b" ", b"", b"x"):
                feed = Feed(self.manifest, self.packs)
                url = getattr(feed, target)
                feed.objects[url] = feed.objects[url][:-1] + suffix
                with self.subTest(target=target, suffix=suffix), self.assertRaises(u.UpdateError):
                    feed.source().latest()

    def test_manifest_identity_requires_exact_channel_tag_version_platform(self):
        for field, value in (("schema", True), ("launcher", 1.0), ("release_tag", "v4.0.13"), ("version", "4.0.13"),
                             ("platform", "macos-arm64"), ("channel", "experimental")):
            modified = dict(self.manifest, **{field: value})
            feed = Feed(self.manifest, self.packs, raw_manifest=encoded(modified))
            with self.subTest(field=field), self.assertRaises(u.UpdateError):
                feed.source().latest()
        modified = dict(self.manifest)
        modified.pop("release_tag")
        with self.assertRaises(u.UpdateError):
            Feed(self.manifest, self.packs, raw_manifest=encoded(modified)).source().latest()

    def test_duplicate_json_fields_fail_closed(self):
        source = u.CloudflareSource("windows-x64")
        with patch.object(source, "read", return_value=b'{"schema":1,"channel":"stable","channel":"stable","platforms":{}}'):
            with self.assertRaisesRegex(u.UpdateError, "Duplicate"):
                source.latest()

    def test_source_discards_previous_download_urls_when_discovery_fails(self):
        feed = Feed(self.manifest, self.packs)
        source = feed.source()
        source.latest()
        feed.objects[feed.channel_url] = b"broken"
        with self.assertRaises(u.UpdateError):
            source.latest()
        self.assertEqual(source.urls, {})
        self.assertIsNone(source.manifest_digest)

    def test_experimental_channel_requires_reserved_version_and_matching_tag(self):
        manifest = copy.deepcopy(self.manifest)
        manifest.update(version="4.90.1", channel="experimental", release_tag="v4.90.1-preview.1")
        feed = Feed(manifest, self.packs)
        self.assertEqual(feed.source().latest(), manifest)
        feed = Feed(manifest, self.packs, channel_change=lambda c: c.update(release_tag="v4.90.1-preview.2"))
        with self.assertRaises(u.UpdateError):
            feed.source().latest()

    def test_only_exact_pinned_https_routes_are_allowed(self):
        valid = Feed(self.manifest, self.packs).catalog_url
        for url in (valid, valid.replace("downloads.layeredhuman.com", "downloads.layeredhuman.com:443")):
            self.assertEqual(u.cloudflare_url(url), url)
        paths = ["/", "/updates/packs/" + "A"*64 + ".bin", "/updates/channels/draft.json",
                 "/updates/releases/v4.0.12/windows-x64/../x.json", "/updates/channels/%73table.json",
                 "/updates/channels/stable.json/extra"]
        invalid = [u.CLOUDFLARE_ORIGIN + p for p in paths]
        invalid.extend([valid.replace("https:", "http:"), valid + "?token=x", valid + "#x", valid + "?", valid + "#",
                        valid.replace("downloads.layeredhuman.com", "downloads.layeredhuman.com.evil.invalid"),
                        valid.replace("downloads.layeredhuman.com", "evil.invalid"),
                        valid.replace("downloads.layeredhuman.com", "name@downloads.layeredhuman.com"),
                        valid.replace("downloads.layeredhuman.com", "downloads.layeredhuman.com:444"),
                        valid.replace("downloads.layeredhuman.com", "downloads.layeredhuman.com:"),
                        valid.replace("downloads.layeredhuman.com", "downloads.layeredhuman.com:bad"), "\n" + valid])
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(u.UpdateError):
                u.cloudflare_url(url)

    def test_redirects_and_final_response_are_revalidated(self):
        url = f"{u.CLOUDFLARE_ORIGIN}/updates/channels/stable.json"
        request = urllib.request.Request(url)
        redirect = u.CloudflareRedirect()
        redirected = redirect.redirect_request(request, None, 302, "Found", {}, url)
        self.assertEqual(redirected.full_url, url)
        source = u.CloudflareSource("windows-x64")
        for target in (url.replace("downloads.layeredhuman.com", "evil.invalid"),
                       url.replace("https:", "http:"), url.replace("stable", "experimental"), url + "?x=1"):
            with self.subTest(target=target), self.assertRaises(u.UpdateError):
                redirect.redirect_request(request, None, 302, "Found", {}, target)
            source.opener = SimpleNamespace(open=lambda *a, **k: Response(b"{}", target))
            with self.subTest(final_url=target), self.assertRaises(u.UpdateError):
                source.read(url, 2)

    def test_exact_range_bounded_metadata_encoding_and_chunk_request(self):
        feed = Feed(self.manifest, self.packs)
        source = feed.source()
        source.latest()
        blob = next(iter(self.manifest["blobs"].values()))
        total = self.manifest["packs"][blob["pack"]]
        url = source.urls[blob["pack"]]
        for status, headers, raw in ((200, {}, b"x"), (206, {"Content-Range": "bytes 0-1/2"}, b"x"),
                                     (206, {"Content-Range": f"bytes {blob['offset']}-{blob['offset']+blob['size']-1}/{total}"}, b"x")):
            source.opener = SimpleNamespace(open=lambda *a, **k: Response(raw, url, status, headers))
            with self.subTest(status=status, headers=headers), self.assertRaises(u.UpdateError):
                source.chunk(blob, total)
        for args in ((dict(blob, offset=-1), total), (dict(blob, size=u.CHUNK_SIZE+65537), total),
                     (blob, total+1), (dict(blob, pack="unknown"), total)):
            with self.subTest(args=args), self.assertRaises(u.UpdateError):
                source.chunk(*args)
        url = source.channel_url
        for status, headers, raw in ((200, {}, b"x"*11), (206, {}, b"{}"),
                                     (200, {"Content-Encoding": "gzip"}, b"{}")):
            source.opener = SimpleNamespace(open=lambda *a, **k: Response(raw, url, status, headers))
            with self.subTest(status=status, headers=headers), self.assertRaises(u.UpdateError):
                source.read(url, 10)


class BridgeLifecycleTests(unittest.TestCase):
    def test_immutable_github_bridge_then_cloudflare_changed_model_and_rollback(self):
        legacy_path = Path(__file__).parent / "fixtures/legacy_updater_v3_1_1.py"
        before = hashlib.sha256(legacy_path.read_bytes()).hexdigest()
        spec = importlib.util.spec_from_file_location("cloudflare_immutable_fixture", legacy_path)
        legacy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(legacy)
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture_root(tmp)
            base = root / "install"
            (base / "_internal/data/anatomy").mkdir(parents=True)
            (base / "AnatomyExplorer.exe").write_bytes(b"immutable original bootstrap")
            (base / "_internal/VERSION").write_text("4.0.11")
            model = os.urandom(u.CHUNK_SIZE*2+321)
            (base / "_internal/data/anatomy/model.bin").write_bytes(model)
            (base / "_internal/data/anatomy/obsolete.npz").write_bytes(b"retired")
            create_payload(base, root / "basepacks", "4.0.11")
            protected = root / "user/notes.json"
            protected.parent.mkdir()
            protected.write_text('{"notes":"keep"}')
            library = root / "model-library/personal.npz"
            library.parent.mkdir()
            library.write_bytes(b"personal model")
            bridge = root / "bridge"
            shutil.copytree(base, bridge)
            (bridge / "AnatomyExplorer.exe").write_bytes(b"bridge application with CloudflareSource")
            (bridge / "_internal/VERSION").write_text("4.0.12")
            bridge_packs = root / "bridgepacks"
            bridge_manifest = create_payload(bridge, bridge_packs, "4.0.12")
            raw = encoded(u.legacy_manifest(bridge_manifest))
            prefix = f"https://github.com/{legacy.REPO}/releases/download/v4.0.12/"
            assets = [{"name": legacy.MANIFEST, "size": len(raw), "digest": "sha256:"+u.sha(raw),
                       "browser_download_url": prefix+legacy.MANIFEST}]
            assets.extend({"name": name, "size": size, "browser_download_url": prefix+name}
                          for name, size in bridge_manifest["packs"].items())
            release = {"tag_name": "v4.0.12", "draft": False, "prerelease": False, "assets": assets}
            legacy_source = legacy.GitHubSource("windows-x64")
            requests = []
            def github_read(url, limit, headers=None, expected_range=None):
                requests.append(url)
                if url == legacy.API:
                    return encoded(release)
                if url == prefix + legacy.MANIFEST:
                    return raw
                name = url.removeprefix(prefix)
                data = (bridge_packs / name).read_bytes()
                start, end = map(int, headers["Range"].removeprefix("bytes=").split("-"))
                self.assertEqual(expected_range, f"bytes {start}-{end}/{len(data)}")
                return data[start:end+1]
            legacy_source.read = github_read
            old_store = legacy.UpdateStore(base, root / "updates")
            old_store.prepare(legacy_source.latest(), legacy_source)
            old_store.activate()
            old_store.healthy()
            store = u.UpdateStore(base, old_store.root)
            bridge_identity = store.state()["current"]
            candidate = root / "candidate"
            shutil.copytree(bridge, candidate)
            (candidate / "_internal/VERSION").write_text("4.0.13")
            changed = bytearray(model)
            changed[u.CHUNK_SIZE+100] ^= 1
            (candidate / "_internal/data/anatomy/model.bin").write_bytes(changed)
            (candidate / "_internal/data/anatomy/obsolete.npz").unlink()
            (candidate / "_internal/data/anatomy/new.npz").write_bytes(b"new regional model")
            packs = root / "nextpacks"
            manifest = create_payload(candidate, packs, "4.0.13")
            feed = Feed(manifest, packs)
            source = feed.source()
            result = store.prepare(source.latest(), source)
            self.assertEqual(result["status"], "ready")
            self.assertLess(result["downloaded"], u.CHUNK_SIZE+10000)
            self.assertGreater(result["reused"], u.CHUNK_SIZE)
            self.assertEqual(store.state()["current"], bridge_identity)
            self.assertTrue(all(url.startswith(u.CLOUDFLARE_ORIGIN) for url, _ in feed.requests))
            self.assertTrue(requests and all("github" in url for url in requests))
            active = old_store.activate()  # immutable base remains supervisor
            self.assertEqual((active / "_internal/data/anatomy/model.bin").read_bytes(), changed)
            self.assertFalse((active / "_internal/data/anatomy/obsolete.npz").exists())
            self.assertTrue((active / "_internal/data/anatomy/new.npz").exists())
            old_store.healthy()
            store.request_rollback()
            old_store.rollback()
            self.assertEqual(store.state()["current"], bridge_identity)
            self.assertEqual(protected.read_text(), '{"notes":"keep"}')
            self.assertEqual(library.read_bytes(), b"personal model")
            self.assertEqual((base / "AnatomyExplorer.exe").read_bytes(), b"immutable original bootstrap")
            self.assertEqual((base / "_internal/VERSION").read_text(), "4.0.11")
        self.assertEqual(hashlib.sha256(legacy_path.read_bytes()).hexdigest(), before)


class PrivateStageTests(unittest.TestCase):
    setUp = CloudflareTests.setUp
    def stage(self, store):
        identity = self.manifest["version"] + "-" + u.sha(encoded(self.manifest))[:16]
        stage = store.versions / (identity + ".staging")
        stage.mkdir(parents=True)
        return stage

    def store(self):
        base = self.root / "base"
        shutil.copytree(self.bundle, base)
        (base / "_internal/VERSION").write_text("4.0.11")
        create_payload(base, self.root / "basepacks", "4.0.11")
        return u.UpdateStore(base, self.root / "updates")

    def test_resumed_stage_prunes_obsolete_files_and_bytecode_before_publication(self):
        store = self.store()
        stage = self.stage(store)
        (stage / "_internal/stale").mkdir(parents=True)
        (stage / "_internal/stale/injected.py").write_text("unlisted executable code")
        (stage / "_internal/__pycache__").mkdir()
        (stage / "_internal/__pycache__/old.pyc").write_bytes(b"cache")
        (stage / "_internal/UPDATE_CHANNEL.json").write_text('{"channel":"experimental"}')
        source = Feed(self.manifest, self.packs).source()
        store.prepare(source.latest(), source)
        pending = store.path(store.state()["pending"])
        self.assertFalse((pending / "_internal/stale").exists())
        self.assertFalse((pending / "_internal/__pycache__").exists())
        self.assertFalse((pending / "_internal/UPDATE_CHANNEL.json").exists())
        self.assertEqual(store.active(), store.base)

    def test_pruning_is_bounded_and_never_publishes_on_failure(self):
        store = self.store()
        stage = self.stage(store)
        for index in range(3):
            (stage / f"extra{index}").write_bytes(b"extra")
        source = Feed(self.manifest, self.packs).source()
        with patch.object(u, "MAX_STAGE_PRUNE", 2), self.assertRaisesRegex(u.UpdateError, "too many"):
            store.prepare(source.latest(), source)
        self.assertIsNone(store.state().get("pending"))
        self.assertTrue(all((stage / f"extra{index}").exists() for index in range(3)))

    def test_private_stage_rejects_links_without_deleting_the_target(self):
        store = self.store()
        stage = self.stage(store)
        target = self.root / "protected.txt"
        target.write_bytes(b"keep")
        try:
            (stage / "injected").symlink_to(target)
        except OSError:
            self.skipTest("Symlinks require Windows developer mode or elevated fixture process")
        source = Feed(self.manifest, self.packs).source()
        with self.assertRaisesRegex(u.UpdateError, "Unexpected link"):
            store.prepare(source.latest(), source)
        self.assertEqual(target.read_bytes(), b"keep")
        self.assertIsNone(store.state().get("pending"))

    def test_running_bytecode_does_not_break_live_verification_or_rollback(self):
        store = self.store()
        source = Feed(self.manifest, self.packs).source()
        store.prepare(source.latest(), source)
        active = store.activate()
        cache = active / "_internal/__pycache__"
        cache.mkdir()
        (cache / "updater.cpython-311.pyc").write_bytes(b"ordinary runtime cache")
        store.verify(active)
        u.check_private_inventory(active, self.manifest, allow_runtime_cache=True)
        store.healthy()
        store.request_rollback()
        self.assertTrue(store.rollback())
        self.assertEqual(store.active(), store.base)


if __name__ == "__main__":
    unittest.main()
