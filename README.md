# rust-target-size

Code for the post "Taming Rust's target/ Directory". Why Rust `target/` directories grow to tens of gigabytes, what actually helps, and a
tool that removes stale build artifacts without touching the ones you use.

Write-up with all results: https://sametdemir.com/programming/taming-rust-target-directory/

## target-gc

`cargo clean` deletes everything; age-based cleaners can't tell a stale artifact from
a live one that is merely old. `target-gc` asks cargo which artifacts your builds use
and deletes the rest.

```sh
curl -LO https://raw.githubusercontent.com/sametd/rust-target-size/main/target-gc
chmod +x target-gc

./target-gc --dry-run      # in a cargo project: what would be removed
./target-gc                # remove it
```

**How:** it runs your usual cargo commands with `--message-format=json`. Cargo reports
every artifact a build uses, including up-to-date ones; their hashes are the live set.
In the profile directories those commands used, everything in `deps/`, `examples/`,
`build/` and `.fingerprint/` that isn't live is deleted, plus surplus `incremental/`
directories. The next build is a no-op.

**Which commands:** by default `build --workspace --all-targets`, `test --workspace
--no-run` and `check --workspace --all-targets`. Pass your own after `--`:

```sh
./target-gc -- "build --workspace" "test --no-run --features foo" "build --release"
```

Profile directories that none of the commands touch (often `release/`) are left alone.

Marking runs the commands for real, so if something they need is not built yet, it gets
built first, even with `--dry-run`. Nothing is deleted until marking succeeds.

**Shared target directory:** pass every project that uses it, otherwise their
artifacts look dead:

```sh
./target-gc --manifest-path ~/a/Cargo.toml --manifest-path ~/b/Cargo.toml
```

Single file, Python 3.8+, no dependencies. Tested on Linux.

## What helps (measured)

A demo service (axum, tokio, reqwest, tonic/OpenTelemetry, NATS, JWT; 358 crates,
24 integration test files), one scripted dev session per configuration, Rust 1.98:

| recipe | target/ | edit, rebuild tests |
|---|---:|---:|
| defaults | 8.19 GiB | 7.0 s |
| 1. dependencies without debug info + `split-debuginfo = "unpacked"` | 3.14 GiB | 2.9 s |
| 2. recipe 1 + one integration test binary (`tests/it/main.rs`) | 1.76 GiB | 1.0 s |
| 3. one test binary, `line-tables-only`, deps without debug info | 1.56 GiB | 0.9 s |
| 4. full debug info, one test binary, unpacked, zlib-compressed links | 2.45 GiB | 1.2 s |
| CI: incremental off, line tables, deps without debug, one test binary | 6.72 → 1.12 GiB | |

Details, trade-offs and the things that don't work (zstd debug compression breaks
Rust backtraces) are in the write-up.

## Reproducing

Needs: Rust stable plus the `nightly` and `1.99.0` toolchains (`rustup toolchain install`),
gdb for the debuggability checks, and for the extra experiments
[sccache](https://github.com/mozilla/sccache) (`many_projects.py`) and
[cargo-sweep](https://github.com/holmgr/cargo-sweep) (`aging.sh`).

```
demo/                     the benchmark workspace
scripts/measure.py        one dev session -> results/<scenario>.json
scripts/gen_tests.py      the 24 tests as 24 binaries (split) or 1 (single)
scripts/run_all.sh        the full matrix (~1 h on 20 cores, ~12 GB free disk)
scripts/many_projects.py  two projects: separate vs shared target dir vs sccache
scripts/aging.sh          age a target dir, then compare cleaners
scripts/chart.py          results/summary.json -> results/chart.svg
results/                  raw data
```

```sh
cd scripts && ./run_all.sh
python3 measure.py my-try --layout single --config 'profile.dev.package."*".debug=false'
```

Sizes are allocated disk blocks with hardlinks counted once. In `results/nightly-*.json`
cargo uses its new `build/<package>/<hash>/` layout; the categories account for that.

## License

MIT OR Apache-2.0, at your option.
