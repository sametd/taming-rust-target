//! `RUST_BACKTRACE=1 cargo run --example backtrace` must show svc-core/src/lib.rs:LINE.
fn main() {
    let depth = std::env::args().nth(1).and_then(|s| s.parse().ok()).unwrap_or(3);
    println!("{}", svc_core::explode(depth));
}
