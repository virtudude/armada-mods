# The native GPU host replaces the shared WebKit host for this mod.
# Replace the generic source-tree stage with explicitly named runtime inputs.
python3 "$ROOT/$MOD/native/package.py" stage "$ROOT/$MOD" "$STAGE"
host_triple=$(rustc -vV | sed -n 's/^host: //p')
[[ "$host_triple" == aarch64-unknown-linux-gnu ]] || die "native Pip-Boy currently builds on an ARM64 Linux Rust host"
native_target="$ROOT/build/fallout4-native"
CARGO_TARGET_DIR="$native_target" cargo build --release --locked --manifest-path "$ROOT/$MOD/native/Cargo.toml"
install -D -m 0755 "$native_target/release/armada-pipboy" "$STAGE/host/pipboy-host"
cargo metadata --locked --filter-platform "$host_triple" --format-version 1 --manifest-path "$ROOT/$MOD/native/Cargo.toml" > "$ROOT/build/pipboy-dependencies.json"
python3 "$ROOT/$MOD/native/licenses.py" "$ROOT/build/pipboy-dependencies.json" "$STAGE/licenses"
python3 "$ROOT/$MOD/native/package.py" check "$ROOT/$MOD" "$STAGE"
