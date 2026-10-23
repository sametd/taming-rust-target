# taming-rust-target

`target-gc` deletes stale cargo build artifacts and keeps the ones you still use.
Plus the benchmark behind [Taming Rust's target/ Directory](https://sametdemir.com/programming/taming-rust-target-directory/).

## target-gc

```sh
curl -LO https://raw.githubusercontent.com/sametd/taming-rust-target/main/target-gc
chmod +x target-gc

./target-gc --dry-run    # in a cargo project: show what would be removed
./target-gc              # remove it
```

It runs your cargo commands with `--message-format=json`, keeps every artifact cargo
reports as used, and deletes the rest. The next build compiles nothing.

Default commands: `build --workspace --all-targets`, `test --workspace --no-run`,
`check --workspace --all-targets`. Use your own after `--`:

```sh
./target-gc -- "build --workspace" "test --no-run --features foo" "build --release"
```

- Profile directories none of the commands use (often `release/`) are not touched.
- Missing artifacts are built first, also with `--dry-run`.
- Shared target directory: pass every project that uses it.

  ```sh
  ./target-gc --manifest-path ~/a/Cargo.toml --manifest-path ~/b/Cargo.toml
  ```

Single Python 3.8+ file, no dependencies. Tested on Linux.

## Smaller target/ in the first place

```toml
# ~/.cargo/config.toml
[profile.dev]
split-debuginfo = "unpacked"   # one copy of debug info instead of one per binary

[profile.dev.package."*"]
debug = false                  # no debug info for dependencies; your crates keep it
```

Then put integration tests in one binary: `tests/it/main.rs` with `mod` lines.

On the benchmark (358 crates, 24 test files), together: 8.19 GiB → 1.76 GiB, and
rebuilding tests after an edit 7.0 s → 1.0 s. Details and other options in the post.

## Benchmark

```sh
cd scripts
./run_all.sh                     # full matrix, ~1 h on 20 cores, ~12 GB disk
python3 compare_cleaners.py       # cleaners on an aged target/ (needs cargo-sweep, cargo-target-gc, reflink fs)
python3 measure.py my-try --layout single --config 'profile.dev.package."*".debug=false'
```

Needs Rust stable, `nightly` and `1.99.0` toolchains, and gdb. `many_projects.py` also
needs [sccache](https://github.com/mozilla/sccache), `aging.sh` needs
[cargo-sweep](https://github.com/holmgr/cargo-sweep). Raw results are in `results/`.

## License

[Apache-2.0](LICENSE)
