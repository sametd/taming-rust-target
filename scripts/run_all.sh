#!/usr/bin/env bash
# Full matrix (v2 harness: inode-deduplicated sizes, layout-aware categories).
set -u
cd "$(dirname "$0")"
M="python3 measure.py"
DEPS='profile.dev.package."*".debug=false'
OWN_LT='profile.dev.debug="line-tables-only"'
UNPACKED='profile.dev.split-debuginfo="unpacked"'
ZLIB='target.x86_64-unknown-linux-gnu.rustflags=["-C","link-arg=-Wl,--compress-debug-sections=zlib"]'
ZSTD='target.x86_64-unknown-linux-gnu.rustflags=["-C","link-arg=-Wl,--compress-debug-sections=zstd"]'

# techniques alone
$M baseline
$M no-incremental        --config 'profile.dev.incremental=false'
$M split-unpacked        --config "$UNPACKED"
$M link-zlib             --config "$ZLIB"
$M link-zstd             --config "$ZSTD"
$M debug-line-tables     --config "$OWN_LT"
$M deps-no-debug         --config "$DEPS"
$M single-test-binary    --layout single
$M debug-none            --config 'profile.dev.debug=false'
# combinations / recipe candidates
$M single+deps-no-debug              --layout single --config "$DEPS"
$M single+deps-no-debug+unpacked     --layout single --config "$DEPS" --config "$UNPACKED"
$M single+line-tables+deps-none      --layout single --config "$OWN_LT" --config "$DEPS"
$M single+link-zlib                  --layout single --config "$ZLIB"
$M single+unpacked+link-zlib         --layout single --config "$UNPACKED" --config "$ZLIB"
# CI sessions (CI=true -> incremental off): build + test, no check, no edit loop
$M ci-baseline                       --ci
$M ci-recipe                         --ci --layout single --config "$OWN_LT" --config "$DEPS"
# nightly: metadata embedding on (old behaviour) vs off (nightly default)
$M nightly-embed-yes                 --toolchain nightly -Z embed-metadata=yes
$M nightly-embed-no                  --toolchain nightly -Z embed-metadata=no
$M nightly-disk-critical             --toolchain nightly -Z embed-metadata=no --layout single --config "$OWN_LT" --config "$DEPS"
echo ALL-DONE
