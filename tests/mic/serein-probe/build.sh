#!/data/data/com.termux/files/usr/bin/bash
# Builds serein-mic-probe from Serein's pinned audio sources, in native Termux.
# Needs: rust, pkg-config, alsa-lib. Usage: build.sh [work-directory]
set -eu
tag=v1.0.0-nightly.20261028.68
commit_url=https://raw.githubusercontent.com/ViceVerse-cz/Serein/$tag
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
work=${1:-$HOME/.cache/livecd-serein-probe}
android_cfg='any(target_os = "linux", target_os = "android")'

mkdir -p "$work/src/audio" "$work/model/src" "$work/platform/src"
cp "$here/main.rs" "$work/src/main.rs"
fetch() { curl -fsSL "$commit_url/$1" -o "$work/$2"; }
fetch crates/discord-voice/src/activity.rs src/activity.rs
fetch crates/discord-voice/src/diagnostics.rs src/diagnostics.rs
fetch crates/discord-voice/src/audio.rs src/audio.rs
fetch crates/discord-voice/src/audio/echo.rs src/audio/echo.rs
fetch crates/model/src/voice_settings.rs model/src/voice_settings.rs
fetch crates/platform/src/audio.rs platform/src/audio.rs
fetch Cargo.lock Cargo.lock
# Serein keeps its PulseAudio buffer sizes behind this cfg; the rest is target-neutral.
sed -i "s/target_os = \"linux\"/$android_cfg/g" "$work/src/audio.rs"

echo 'pub mod voice_settings;' > "$work/model/src/lib.rs"
echo 'pub mod audio;' > "$work/platform/src/lib.rs"
cat > "$work/model/Cargo.toml" <<'EOF'
[package]
name = "model"
version = "0.0.0"
edition = "2024"
[dependencies]
serde = { version = "1", features = ["derive"] }
EOF
cat > "$work/platform/Cargo.toml" <<'EOF'
[package]
name = "platform"
version = "0.0.0"
edition = "2024"
[dependencies]
cpal = { version = "=0.18.2", default-features = false }
EOF
cat > "$work/Cargo.toml" <<'EOF'
[package]
name = "serein-mic-probe"
version = "0.0.0"
edition = "2024"
[dependencies]
cpal = { version = "=0.18.2", default-features = false, features = ["pulseaudio"] }
model = { path = "model" }
platform = { path = "platform" }
nnnoiseless = { version = "=0.5.2", default-features = false }
rtrb = "=0.4.0"
sonora = { version = "=0.2.0", default-features = false }
tokio = { version = "1", default-features = false, features = ["sync"] }
[patch.crates-io]
cpal = { path = "vendor/cpal" }
[profile.release]
debug = 0
EOF

# cpal's Android target only has AAudio. As in Termux's Alacritty recipe, build its Linux
# code for Android instead, which selects the PulseAudio host.
crate=$work/cpal-0.18.2.crate
curl -fsSL https://static.crates.io/crates/cpal/cpal-0.18.2.crate -o "$crate"
rm -rf "$work/vendor"; mkdir -p "$work/vendor"
tar -xzf "$crate" -C "$work/vendor"; mv "$work/vendor/cpal-0.18.2" "$work/vendor/cpal"
find "$work/vendor/cpal" -type f \( -name '*.rs' -o -name Cargo.toml \) -print0 | xargs -0 sed -i \
    -e 's/"android"/"disabling_this_because_it_is_for_building_an_apk"/g' \
    -e 's/"linux"/"android"/g'
# LIVECD_PROBE_CPAL=stock reproduces the start-up stall this patch fixes.
if [ "${LIVECD_PROBE_CPAL:-patched}" != stock ]; then
    patch -d "$work/vendor/cpal" -p1 < "$here/cpal-record-queue.patch"
fi

cd "$work"
nice -n 19 cargo build --release -j "${LIVECD_PROBE_JOBS:-4}"
echo "Built: $work/target/release/serein-mic-probe"
