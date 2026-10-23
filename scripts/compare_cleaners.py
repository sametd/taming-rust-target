#!/usr/bin/env python3
"""Compare target/ cleaners (needs cargo-sweep and cargo-target-gc installed) from an identical, realistically aged starting point.

Aging timeline (default dev settings, file times backdated per step):
  60 d  weeks on Rust 1.98 (stable)
  30 d  rustup update -> 1.99          <- most of the live build is from here
  21 d  opt-level = 1 experiment, reverted
  14 d  hyper 1.10 for a while
   7 d  a release build
   0 d  back on hyper 1.12; 5 edit -> test cycles; current session

"Normal use" = build/test --no-run/check --all-targets on 1.99. For every cleaner:
restore the aged snapshot (XFS reflink), run the cleaner, measure what is left,
then run the normal session and count what had to be recompiled, plus a release build.
"""
import json, os, re, shutil, subprocess, sys, time
from pathlib import Path

R = Path(__file__).resolve().parent.parent
DEMO = R / "demo"
T = DEMO / "target"
SNAP = Path.home() / ".cache/taming-rust-target/aged-snapshot"   # needs a reflink-capable fs (XFS, Btrfs)
PYGC = R / "target-gc"
G = 2**30
NORMAL = ["build --workspace --all-targets", "test --workspace --no-run", "check --workspace --all-targets"]
ENV = dict(os.environ, RUSTUP_TOOLCHAIN="1.99.0",
           CARGO_TERM_COLOR="never", LC_ALL="C")
ENV.pop("CARGO_TARGET_DIR", None)


def sh(cmd, env=ENV, check=True, cwd=DEMO):
    t = time.perf_counter()
    p = subprocess.run(cmd, shell=isinstance(cmd, str), cwd=cwd, env=env, capture_output=True, text=True)
    if check and p.returncode:
        sys.exit(f"FAILED ({p.returncode}): {cmd}\n{p.stdout[-2000:]}\n{p.stderr[-3000:]}")
    return p, time.perf_counter() - t


def du(p):
    seen, n = set(), 0
    for dp, _, fs in os.walk(p):
        for f in fs:
            st = os.lstat(os.path.join(dp, f))
            if (st.st_dev, st.st_ino) not in seen:
                seen.add((st.st_dev, st.st_ino)); n += st.st_blocks * 512
    return n


def backdate(since, days):
    t = time.time() - days * 86400
    for dp, dns, fns in os.walk(T):
        for n in fns + dns:
            p = os.path.join(dp, n)
            try:
                if os.lstat(p).st_mtime >= since:
                    os.utime(p, (t, t), follow_symlinks=False)
            except FileNotFoundError:
                pass


def session(tc="1.99.0", extra=()):
    env = dict(ENV, RUSTUP_TOOLCHAIN=tc)
    compiled, secs = 0, 0.0
    for c in NORMAL:
        p, dt = sh(f"cargo {c} {' '.join(extra)}", env=env)
        compiled += p.stderr.count("Compiling ")
        secs += dt
    return compiled, secs


def age():
    shutil.rmtree(T, ignore_errors=True)
    lock = (DEMO / "Cargo.lock").read_text()
    lib = DEMO / "crates/svc/src/lib.rs"
    src = lib.read_text()
    steps = []
    def step(name, days, fn):
        m = time.time(); fn(); backdate(m, days) if days else None
        steps.append((name, days, round(du(T) / G, 2))); print("  aged:", steps[-1], flush=True)
    step("weeks on Rust 1.98", 60, lambda: session("stable"))
    step("rustup update to 1.99", 30, lambda: session())
    step("opt-level = 1 experiment", 21, lambda: session(extra=["--config", "profile.dev.opt-level=1"]))
    def hyper_old():
        sh("cargo update -q -p hyper --precise 1.10.0"); session()
    step("hyper 1.10", 14, hyper_old)
    step("a release build", 7, lambda: sh("cargo build --workspace --release"))
    def today():
        (DEMO / "Cargo.lock").write_text(lock); session()
        for i in range(5):
            lib.write_text(src + f"\npub const EDIT_{i}: u32 = {i};\n")
            sh("cargo test --workspace --no-run")
        lib.write_text(src); session()
    step("today: hyper 1.12, 5 edit cycles, current session", 0, today)
    return steps


TRIALS = {
    "no cleaning": None,
    "cargo clean": "cargo clean",
    "cargo sweep --time 14": "cargo sweep --time 14",
    "cargo sweep --toolchains (1.99)": "cargo sweep --toolchains 1.99.0-x86_64-unknown-linux-gnu",
    "cargo-target-gc clean": "cargo target-gc clean --confirm",
    "cargo-target-gc clean --stale": "cargo target-gc clean --stale --confirm",
    "target-gc.py": f"{PYGC}",
}


def trial(name, cmd):
    shutil.rmtree(T, ignore_errors=True)
    subprocess.run(["cp", "-a", "--reflink=always", str(SNAP), str(T)], check=True)
    before = du(T)
    out, tool_s, ok = "", 0.0, True
    if cmd:
        p, tool_s = sh(cmd, check=False)
        ok = p.returncode == 0
        out = (p.stdout + p.stderr)[-1500:]
    after = du(T)
    release_after = du(T / "release") if (T / "release").exists() else 0
    compiled, rebuild_s = session()
    p, rel_s = sh("cargo build --workspace --release")
    rel_compiled = p.stderr.count("Compiling ")
    r = dict(name=name, cmd=cmd, ok=ok, before_gib=round(before / G, 2), after_gib=round(after / G, 2),
             freed_gib=round((before - after) / G, 2), release_left_gib=round(release_after / G, 2),
             tool_s=round(tool_s, 1), next_session_recompiled=compiled, next_session_s=round(rebuild_s, 1),
             release_recompiled=rel_compiled, release_s=round(rel_s, 1), output_tail=out)
    print(f"{name:34s} freed {r['freed_gib']:6.2f} | left {r['after_gib']:6.2f} | tool {r['tool_s']:5.1f}s | "
          f"next session: {compiled:4d} crates, {r['next_session_s']:5.1f}s | release: {rel_compiled:3d} crates | ok={ok}",
          flush=True)
    return r


def main():
    SNAP.parent.mkdir(parents=True, exist_ok=True)
    if not SNAP.exists():
        print("aging...", flush=True)
        steps = age()
        subprocess.run(["cp", "-a", "--reflink=always", str(T), str(SNAP)], check=True)
        (R / "results/cleaners_aging.json").write_text(json.dumps(steps, indent=1))
    # live minimum: the normal session (+ release) from empty
    shutil.rmtree(T, ignore_errors=True)
    _, fresh_s = session(); sh("cargo build --workspace --release")
    live = du(T)
    print(f"live minimum (normal session + release, from empty): {live / G:.2f} GiB, session {fresh_s:.1f}s", flush=True)
    results = [trial(n, c) for n, c in TRIALS.items()]
    shutil.rmtree(T, ignore_errors=True)
    (R / "results/cleaners.json").write_text(json.dumps(dict(live_gib=round(live / G, 2), fresh_session_s=round(fresh_s, 1),
                                                          trials=results), indent=1))
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
