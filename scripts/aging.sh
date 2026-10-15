#!/usr/bin/env bash
# Let a target dir age like a real one, then compare cleaners.
#   1. a few weeks on Rust 1.98         (build, tests, rust-analyzer check)
#   2. rustup update -> 1.99            (same session again)
#   3. a profile experiment             (opt-level = 1 for a day, then reverted)
#   4. a dependency bump                (hyper 1.10 -> 1.12: hyper + everything above it)
# Then: cargo-sweep (dry runs) vs target-gc, and prove the next build is a no-op.
# Uses deps-without-debuginfo to keep the experiment within free disk space;
# the GC logic doesn't depend on debuginfo settings.
set -eu
export LC_ALL=C
HERE="$(cd "$(dirname "$0")/.." && pwd)"
D="$HERE/demo"
export CARGO_TARGET_DIR="$HOME/.cache/rts/aging"
OUT="$HERE/results/aging.txt"
gib() { du -sb "$CARGO_TARGET_DIR" | awk '{printf "%.2f GiB", $1/2^30}'; }
session() { # toolchain [extra args]
  local tc=$1; shift
  cargo +$tc build --workspace --all-targets -q "$@"
  cargo +$tc test --workspace --no-run -q "$@" 2>/dev/null
  cargo +$tc check --workspace --all-targets -q "$@"
}
log() { echo "$*" | tee -a "$OUT"; }

cd "$D"
python3 "$HERE/scripts/gen_tests.py" crates/svc split >/dev/null
mkdir -p .cargo && printf '[profile.dev.package."*"]\ndebug = false\n' > .cargo/config.toml
LOCK_BACKUP=$(mktemp); cp Cargo.lock "$LOCK_BACKUP"
rm -rf "$CARGO_TARGET_DIR"; : > "$OUT"

session stable;                                    log "after weeks on 1.98:        $(gib)"
session 1.99.0;                                   log "after rustup update (1.99): $(gib)"
session 1.99.0 --config profile.dev.opt-level=1;  log "after opt-level experiment: $(gib)"
cargo update -q -p hyper --precise 1.10.0
session 1.99.0;                                   log "after building on hyper 1.10: $(gib)"
cp "$LOCK_BACKUP" Cargo.lock
session 1.99.0;                                   log "back on hyper 1.12 (current): $(gib)"
AGED=$(du -sb "$CARGO_TARGET_DIR" | cut -f1)

log ""
log "--- cleaners (dry runs first) ---"
log "cargo sweep --installed:      $(cargo sweep --installed --dry-run 2>&1 | grep -iE 'clean|would' | tail -1)"
log "cargo sweep --toolchains 1.99.0-x86_64-unknown-linux-gnu: $(cargo sweep --toolchains 1.99.0-x86_64-unknown-linux-gnu --dry-run 2>&1 | grep -iE 'would clean' | tail -1)"
log "cargo sweep --time 1:         $(cargo sweep --time 1 --dry-run 2>&1 | grep -iE 'clean|would' | tail -1)"
log "target-gc --dry-run:          $(RUSTUP_TOOLCHAIN=1.99.0 "$HERE/target-gc" --dry-run 2>&1 | tail -1)"

log ""
log "--- target-gc for real ---"
RUSTUP_TOOLCHAIN=1.99.0 "$HERE/target-gc" 2>&1 | tee -a "$OUT"
log "size after target-gc: $(gib)  (was $(echo "$AGED" | awk '{printf "%.2f GiB", $1/2^30}'))"

log ""
log "--- is the next build a no-op? (count of 'Compiling' lines) ---"
for c in "build --workspace --all-targets" "test --workspace --no-run" "check --workspace --all-targets"; do
  n=$(cargo +1.99.0 $c 2>&1 | grep -c "Compiling" || true)
  log "cargo $c: $n crates recompiled"
done
n=$(cargo +1.99.0 test --workspace 2>&1 | grep -oE "test result: ok\. [0-9]+ passed" | awk '{s+=$4} END {print s}')
log "cargo test: $n tests passed"

rm -rf .cargo "$CARGO_TARGET_DIR"
echo AGING-DONE
