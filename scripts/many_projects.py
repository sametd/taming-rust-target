#!/usr/bin/env python3
"""Two different projects with the same dependency stack:
separate target dirs vs one shared target dir vs sccache (separate dirs, shared cache).

Workload per project: cargo build --workspace + cargo test --workspace --no-run.
Writes results/many_projects.json.
"""
import json, os, pathlib, re, shutil, subprocess, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
A = ROOT / "demo"
B = pathlib.Path.home() / ".cache/rts-src/orders"
T = pathlib.Path.home() / ".cache/rts"
CACHE = pathlib.Path.home() / ".cache/rts-sccache"
SCCACHE = shutil.which("sccache") or str(pathlib.Path.home() / ".local/bin/sccache")
GEN = ROOT / "scripts/gen_tests.py"
GiB = 2**30

SETTINGS = {
    "default": ("split", []),
    "recipe": ("single", ["--config", 'profile.dev.package."*".debug=false']),
}


def du(p: pathlib.Path) -> int:
    seen, total = set(), 0
    for dp, _, fs in os.walk(p):
        for f in fs:
            st = os.lstat(os.path.join(dp, f))
            if (st.st_dev, st.st_ino) not in seen:
                seen.add((st.st_dev, st.st_ino))
                total += st.st_blocks * 512
    return total


def make_b():
    """B = a different project (other package names) with the same dependencies."""
    shutil.rmtree(B, ignore_errors=True)
    B.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(A, B, ignore=shutil.ignore_patterns("target"))
    core = B / "crates/svc-core/Cargo.toml"
    core.write_text(core.read_text().replace('name = "svc-core"', 'name = "orders-core"') + '\n[lib]\nname = "svc_core"\n')
    svc = B / "crates/svc/Cargo.toml"
    t = svc.read_text().replace('name = "svc"\n', 'name = "orders"\n', 1)
    t = t.replace('svc-core = { version = "0.1.0", path = "../svc-core" }',
                  'svc-core = { package = "orders-core", version = "0.1.0", path = "../svc-core" }')
    marker = "\n# --- generated test layout ---\n"
    head, _, tail = t.partition(marker)
    svc.write_text(head + '\n[lib]\nname = "svc"\n' + (marker + tail if tail else ""))


def session(project, target, extra, wrapper=False):
    env = dict(os.environ, CARGO_TARGET_DIR=str(target), CARGO_TERM_COLOR="never")
    env.pop("RUSTC_WRAPPER", None)
    if wrapper:
        env["RUSTC_WRAPPER"] = SCCACHE
        env["SCCACHE_DIR"] = str(CACHE)
        env["SCCACHE_CACHE_SIZE"] = "50G"
    t = time.perf_counter()
    for cmd in (["build", "--workspace"], ["test", "--workspace", "--no-run"]):
        subprocess.run(["cargo", *cmd, "-q", *extra], cwd=project, env=env, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return round(time.perf_counter() - t, 1)


def sccache(*args):
    env = dict(os.environ, SCCACHE_DIR=str(CACHE), SCCACHE_CACHE_SIZE="50G")
    return subprocess.run([SCCACHE, *args], env=env, capture_output=True, text=True).stdout


def stats():
    s = json.loads(sccache("--show-stats", "--stats-format", "json"))["stats"]
    hits = sum(s["cache_hits"]["counts"].values())
    misses = sum(s["cache_misses"]["counts"].values())
    reasons = s.get("not_cached") or {}
    return {"hits": hits, "misses": misses, "not_cacheable": sum(reasons.values()),
            "compile_requests": s.get("compile_requests", 0), "not_cached_reasons": s.get("not_cached", {})}


def main():
    make_b()
    out = {}
    for name, (layout, extra) in SETTINGS.items():
        for proj in (A, B):
            subprocess.run(["python3", str(GEN), str(proj / "crates/svc"), layout], check=True, stdout=subprocess.DEVNULL)
        r = {}
        # 1. separate target dirs
        for d in ("sep-a", "sep-b", "shared", "scc-a", "scc-b"):
            shutil.rmtree(T / d, ignore_errors=True)
        r["separate"] = {"a_s": session(A, T / "sep-a", extra), "b_s": session(B, T / "sep-b", extra)}
        r["separate"]["gib"] = round((du(T / "sep-a") + du(T / "sep-b")) / GiB, 2)
        # 2. one shared target dir
        r["shared"] = {"a_s": session(A, T / "shared", extra), "b_s": session(B, T / "shared", extra)}
        r["shared"]["gib"] = round(du(T / "shared") / GiB, 2)
        # 3. sccache, separate target dirs, empty cache to start
        sccache("--stop-server"); shutil.rmtree(CACHE, ignore_errors=True); sccache("--start-server")
        a_s = session(A, T / "scc-a", extra, wrapper=True); sa = stats()
        sccache("--zero-stats")
        b_s = session(B, T / "scc-b", extra, wrapper=True); sb = stats()
        # 4. sccache's real selling point: cargo clean, rebuild from cache
        shutil.rmtree(T / "scc-a")
        sccache("--zero-stats")
        a_again = session(A, T / "scc-a", extra, wrapper=True); sa2 = stats()
        r["sccache"] = {"a_s": a_s, "b_s": b_s, "a_after_clean_s": a_again,
                        "stats_a_cold": sa, "stats_b_warm": sb, "stats_a_after_clean": sa2,
                        "targets_gib": round((du(T / "scc-a") + du(T / "scc-b")) / GiB, 2),
                        "cache_gib": round(du(CACHE) / GiB, 2)}
        r["no_cache_after_clean_s"] = None
        shutil.rmtree(T / "sep-a"); r["no_cache_after_clean_s"] = session(A, T / "sep-a", extra)
        sccache("--stop-server")
        out[name] = r
        print(name, json.dumps(r))
        for d in ("sep-a", "sep-b", "shared", "scc-a", "scc-b"):
            shutil.rmtree(T / d, ignore_errors=True)
    shutil.rmtree(CACHE, ignore_errors=True)
    shutil.rmtree(B, ignore_errors=True)
    subprocess.run(["python3", str(GEN), str(A / "crates/svc"), "split"], check=True, stdout=subprocess.DEVNULL)
    (ROOT / "results/many_projects.json").write_text(json.dumps(out, indent=2))
    print("MANY-DONE")


if __name__ == "__main__":
    main()
