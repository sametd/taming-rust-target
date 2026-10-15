#!/usr/bin/env python3
"""Run one reproducible "dev session" against the demo workspace and record
target-dir size, build times and debuggability.

    measure.py <scenario> [--layout split|single] [--config KEY=VALUE ...]
               [--env K=V ...] [--release] [--keep]

Session (all with the scenario's --config flags):
  1. cargo build --workspace                  (dev binary)
  2. cargo test  --workspace --no-run         (all test binaries + examples)
  3. cargo check --workspace --all-targets    (what rust-analyzer runs)
  4. 3x: edit svc/src/lib.rs, cargo test --workspace --no-run   (edit loop)
  5. cargo test --workspace                   (tests still pass?)
  6. backtrace + gdb checks                   (debugging still works?)
  [--release] cargo build --workspace --release
"""
import argparse, json, os, pathlib, re, shutil, statistics, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo"
RESULTS = ROOT / "results"
TARGETS = pathlib.Path.home() / ".cache" / "rts"
EDIT_FILE = DEMO / "crates/svc/src/lib.rs"
CORE = DEMO / "crates/svc-core/src/lib.rs"
# line of the recursive call inside svc_core::explode, used as the gdb breakpoint
BREAK_AT = f"{CORE}:{next(i for i, l in enumerate(CORE.read_text().splitlines(), 1) if 'explode(depth - 1) + 1' in l)}"
GiB = 2**30


def run(cmd, env, cwd=DEMO, check=True):
    t = time.perf_counter()
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    dt = time.perf_counter() - t
    if check and p.returncode != 0:
        sys.stderr.write(p.stdout[-3000:] + p.stderr[-6000:])
        raise SystemExit(f"FAILED: {' '.join(cmd)}")
    return dt, p


def walk_files(path: pathlib.Path):
    """Yield (path, size_on_disk) once per inode: uplifted artifacts are hardlinks."""
    seen = set()
    for dirpath, _, files in os.walk(path):
        for f in files:
            p = os.path.join(dirpath, f)
            try:
                st = os.lstat(p)
            except FileNotFoundError:
                continue
            key = (st.st_dev, st.st_ino)
            if key in seen:
                continue
            seen.add(key)
            yield p, st.st_blocks * 512


def du(path: pathlib.Path) -> int:
    return sum(sz for _, sz in walk_files(path))


def classify(p: str) -> str:
    """Works for both layouts: deps/<name>-<hash>.* and build/<pkg>/<hash>/out/*."""
    name = os.path.basename(p)
    parts = p.split(os.sep)
    if "incremental" in parts:
        return "incremental"
    if name.endswith(".rlib"):
        return "rlib"
    if name.endswith(".rmeta"):
        return "rmeta"
    if name.endswith(".so"):
        return "proc_macro_so"
    if name.endswith((".dwo", ".dwp")):
        return "dwo"
    if "." not in name and os.access(p, os.X_OK):
        return "build_scripts" if name.startswith(("build-script-", "build_script_")) else "executables"
    if "build" in parts and "out" in parts:
        return "build_script_output"   # e.g. C objects from cc/cmake build scripts
    return "other"


def breakdown(target: pathlib.Path) -> dict:
    cats = {k: 0 for k in ("executables", "rlib", "rmeta", "proc_macro_so", "dwo", "incremental",
                           "build_scripts", "build_script_output", "other")}
    count_exec = 0
    dev = target / "debug"
    for p, sz in walk_files(dev) if dev.exists() else []:
        c = classify(p)
        cats[c] += sz
        if c == "executables":
            count_exec += 1
    out = dict(cats)
    out["dev_total"] = sum(cats.values())
    out["release"] = du(target / "release") if (target / "release").exists() else 0
    out["total"] = du(target)
    out["executable_count"] = count_exec
    return out


def debuggability(target: pathlib.Path, env) -> dict:
    exe = target / "debug" / "examples" / "backtrace"
    res = {"backtrace_file_line": None, "gdb_line_breakpoint": None, "gdb_locals": None}
    if not exe.exists():
        return res
    e = dict(env, RUST_BACKTRACE="1")
    p = subprocess.run([str(exe), "2"], env=e, capture_output=True, text=True)
    # Only frame lines ("   at ./…/lib.rs:79:9") prove debuginfo; the "panicked at" line comes from
    # #[track_caller] Location data and is present even without any debuginfo.
    res["backtrace_file_line"] = bool(re.search(r"^\s+at .*svc-core/src/lib\.rs:\d+", p.stderr, re.M))
    res["backtrace_excerpt"] = "\n".join(l for l in p.stderr.splitlines() if "explode" in l or "svc-core" in l)[:600]
    if shutil.which("gdb"):
        g = subprocess.run(
            ["gdb", "-q", "-batch", "-ex", "set debuginfod enabled off",
             "-ex", f"break {BREAK_AT}", "-ex", "run", "-ex", "info args", "-ex", "kill",
             "--args", str(exe), "2"],
            capture_output=True, text=True, timeout=120,
        )
        o = g.stdout + g.stderr
        res["gdb_line_breakpoint"] = "Breakpoint 1, " in o
        res["gdb_locals"] = bool(re.search(r"depth = \d+", o))
        res["gdb_excerpt"] = "\n".join(l for l in o.splitlines() if "Breakpoint" in l or "depth" in l)[:400]
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario")
    ap.add_argument("--layout", default="split", choices=["split", "single"])
    ap.add_argument("--config", action="append", default=[])
    ap.add_argument("--env", action="append", default=[])
    ap.add_argument("--release", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--ci", action="store_true", help="CI session: CI=true, build + test, no check/edit loop")
    ap.add_argument("--target-dir")
    ap.add_argument("--toolchain", help="e.g. nightly -> cargo +nightly")
    ap.add_argument("-Z", dest="zflags", action="append", default=[], help="cargo -Z flag (nightly)")
    a = ap.parse_args()

    subprocess.run([sys.executable, str(ROOT / "scripts/gen_tests.py"), str(DEMO / "crates/svc"), a.layout], check=True)

    target = pathlib.Path(a.target_dir) if a.target_dir else TARGETS / a.scenario
    if target.exists() and not a.target_dir:
        shutil.rmtree(target)
    env = dict(os.environ, CARGO_TARGET_DIR=str(target), CARGO_TERM_COLOR="never")
    env.pop("RUSTFLAGS", None)
    if a.ci:
        env["CI"] = "true"   # also makes cargo default to CARGO_INCREMENTAL=0
    for kv in a.env:
        k, v = kv.split("=", 1)
        env[k] = v
    cfg = [x for c in a.config for x in ("--config", c)]
    tc = [f"+{a.toolchain}"] if a.toolchain else []
    z = [f"-Z{f}" for f in a.zflags]
    CARGO = ["cargo", *tc, *z]

    result = {"scenario": a.scenario, "layout": a.layout, "config": a.config, "env": a.env,
              "zflags": a.zflags, "rustc": subprocess.run(["rustc", *tc, "-V"], capture_output=True, text=True).stdout.strip()}
    times = {}
    times["build"], _ = run([*CARGO, "build", "--workspace", *cfg], env)
    times["test_no_run"], _ = run([*CARGO, "test", "--workspace", "--no-run", *cfg], env)
    if not a.ci:
        times["check_all_targets"], _ = run([*CARGO, "check", "--workspace", "--all-targets", *cfg], env)
    result["size_after_session"] = breakdown(target)

    original = EDIT_FILE.read_text()
    edits = []
    try:
        for i in range(0 if a.ci else 3):
            EDIT_FILE.write_text(original + f"\npub const EDIT_{i}: u32 = {i};\n")
            dt, _ = run([*CARGO, "test", "--workspace", "--no-run", *cfg], env)
            edits.append(dt)
    finally:
        EDIT_FILE.write_text(original)
    times["edit_rebuild_tests_median"] = statistics.median(edits) if edits else None
    times["edit_rebuild_tests_all"] = edits

    dt, p = run([*CARGO, "test", "--workspace", *cfg], env, check=False)
    times["test_run"] = dt
    passed = sum(int(m) for m in re.findall(r"test result: ok\. (\d+) passed", p.stdout))
    result["tests"] = {"ok": p.returncode == 0, "passed": passed}

    result["debug"] = debuggability(target, env)

    if a.release:
        times["release_build"], _ = run([*CARGO, "build", "--workspace", "--release", *cfg], env)

    result["size_final"] = breakdown(target)
    result["times"] = times
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{a.scenario}.json").write_text(json.dumps(result, indent=2))

    s = result["size_final"]
    edit = times['edit_rebuild_tests_median']
    print(f"{a.scenario:30s} dev {s['dev_total']/GiB:5.2f} GiB | exec {s['executables']/GiB:5.2f} ({s['executable_count']}) "
          f"| rlib {s['rlib']/GiB:4.2f} | rmeta {s['rmeta']/GiB:4.2f} | incr {s['incremental']/GiB:4.2f} | build {times['build']:5.1f}s "
          f"| tests {times['test_no_run']:5.1f}s | edit {edit if edit is None else round(edit, 1)}s "
          f"| tests ok={result['tests']['ok']} ({passed}) | bt={result['debug']['backtrace_file_line']} "
          f"gdb_line={result['debug']['gdb_line_breakpoint']} locals={result['debug']['gdb_locals']}")

    if not a.keep and not a.target_dir:
        shutil.rmtree(target, ignore_errors=True)


if __name__ == "__main__":
    main()
