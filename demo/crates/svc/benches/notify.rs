use criterion::{Criterion, criterion_group, criterion_main};
use std::hint::black_box;

fn bench(c: &mut Criterion) {
    let n = svc_core::Notification::new("bench.topic", serde_json::json!({"k": [1, 2, 3]})).unwrap();
    c.bench_function("notification roundtrip", |b| {
        b.iter(|| svc_core::Notification::from_bytes(&black_box(n.to_bytes().unwrap())).unwrap())
    });
}

criterion_group!(benches, bench);
criterion_main!(benches);
