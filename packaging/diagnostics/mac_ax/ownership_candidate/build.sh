#!/usr/bin/env bash
# Bounded diagnostic plugin build; never installs SDK frameworks into the wheel.
set -euo pipefail
task_root="$(pwd)"
candidate_root="$task_root/packaging/build/qt-ownership"
sdk_dir="$candidate_root/sdk"
source_dir="$candidate_root/source"
build_dir="$candidate_root/build"
artifact_dir="$candidate_root/evidence"
mkdir -p "$sdk_dir" "$artifact_dir"
sdk_url='https://download.qt.io/online/qtsdkrepository/mac_x64/desktop/qt6_6112/qt6_6112/qt.qt6.6112.clang_64/6.11.2-0-202608131016qtbase-MacOS-MacOS_15-Clang-MacOS-MacOS_15-X86_64-ARM64.7z'
curl --fail --location --proto '=https' --proto-redir '=https' --max-time 180 "$sdk_url" -o "$candidate_root/sdk.7z"
python - "$candidate_root/sdk.7z" <<'PY'
import hashlib, sys
from pathlib import Path
p=Path(sys.argv[1]); raw=p.read_bytes()
assert len(raw)==31039494
assert hashlib.sha1(raw).hexdigest()=='898a61de33218d55538721ce35c61f973768cb07'
print('Official matching SDK size and digest verified')
PY
if command -v 7zz >/dev/null; then
    7zz x -y "$candidate_root/sdk.7z" "-o$sdk_dir" >/dev/null
elif command -v 7z >/dev/null; then
    7z x -y "$candidate_root/sdk.7z" "-o$sdk_dir" >/dev/null
else
    echo 'Matching SDK extraction requires runner 7zz/7z; no SDK rebuild attempted' >&2
    exit 2
fi
test -f "$sdk_dir/lib/QtGui.framework/Versions/A/Headers/6.11.2/QtGui/private/qaccessiblecache_p.h"
test -f "$sdk_dir/lib/cmake/Qt6BuildInternals/Qt6BuildInternalsConfig.cmake"
git clone --depth 1 --branch v6.11.2 https://github.com/qt/qtbase.git "$source_dir"
test "$(git -C "$source_dir" rev-parse HEAD)" = 'ef55f427f2c8b410d34f8a7681020a3000cf6866'
curl --fail --location --proto '=https' --proto-redir '=https' --max-time 60 'https://codereview.qt-project.org/changes/765434/revisions/c7fd3f34b997bb363be15650647665b3b6b8a5f4/patch' -o "$candidate_root/patch.base64"
python - "$candidate_root/patch.base64" "$artifact_dir/qt-765434-patchset1.patch" <<'PY'
import base64, hashlib, sys
from pathlib import Path
raw=base64.b64decode(Path(sys.argv[1]).read_bytes())
assert hashlib.sha256(raw).hexdigest()=='f3409a797a4d68146f040749f099e975957f94a029b328f7242d860fd31dcda3'
Path(sys.argv[2]).write_bytes(raw)
PY
git -C "$source_dir" apply --check "$artifact_dir/qt-765434-patchset1.patch"
git -C "$source_dir" apply "$artifact_dir/qt-765434-patchset1.patch"
cp -R "$source_dir/LICENSES" "$artifact_dir/LICENSES"
cp -R "$source_dir/src/plugins/platforms/cocoa" "$artifact_dir/modified-cocoa-source"
cp "$task_root/packaging/diagnostics/mac_ax/ownership_candidate/CMakeLists.txt" "$artifact_dir/BUILD_WRAPPER.cmake"
"$sdk_dir/bin/qt-cmake" -S "$task_root/packaging/diagnostics/mac_ax/ownership_candidate" -B "$build_dir" -G Ninja \
    -DQTBASE_SOURCE_DIR="$source_dir" \
    -DCMAKE_BUILD_TYPE=RelWithDebInfo \
    -DCMAKE_OSX_DEPLOYMENT_TARGET=13.0 \
    -DCMAKE_OSX_ARCHITECTURES=arm64 \
    -DCMAKE_INSTALL_PREFIX="$build_dir/stage" \
    -DQT_BUILD_EXAMPLES=OFF -DQT_BUILD_TESTS=OFF
cmake --build "$build_dir" --target QCocoaIntegrationPlugin --parallel 4
test -f "$build_dir/plugins/platforms/libqcocoa.dylib"
cp "$build_dir/plugins/platforms/libqcocoa.dylib" "$artifact_dir/libqcocoa.dylib"
codesign --force --sign - "$artifact_dir/libqcocoa.dylib"
codesign --verify --strict "$artifact_dir/libqcocoa.dylib"
python packaging/diagnostics/mac_ax/ownership_candidate/accept.py "$candidate_root"
