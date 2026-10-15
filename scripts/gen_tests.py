#!/usr/bin/env python3
"""Generate the demo's integration tests in one of two layouts.

  split   tests/tNN_<name>.rs        -> 24 test binaries (the common layout)
  single  tests/it/main.rs + modules -> 1 test binary (matklad's advice)

Same test bodies either way, so size/time differences come only from layout.
"""
import pathlib, shutil, sys, textwrap

NAMES = [
    "health", "openapi", "publish_ok", "publish_unauthorized", "publish_forbidden",
    "publish_bad_topic", "publish_bad_json", "topic_lookup", "notification_roundtrip",
    "jwt_roundtrip", "jwt_expired", "jwt_wrong_secret", "cors_preflight", "compression",
    "timeouts", "not_found", "method_not_allowed", "large_body", "unicode_topic",
    "many_roles", "empty_body", "concurrent_publish", "telemetry_pipeline", "nats_disabled",
]

HELPERS = '''
use axum::body::Body;
use axum::http::{Request, StatusCode};
use http_body_util::BodyExt;
use tower::ServiceExt;

/// Pull the whole stack into this binary, like a real integration test does:
/// OTLP exporter (tonic/prost), NATS client, reqwest, axum.
async fn wire_everything() {
    let _ = svc::telemetry::tracer_provider("http://127.0.0.1:4317");
    if std::env::var("DEMO_NEVER_SET").is_ok() {
        let _ = svc::connect_nats("nats://127.0.0.1:4222").await;
    }
}

async fn call(req: Request<Body>) -> (StatusCode, Vec<u8>) {
    let st = svc::AppState::for_tests();
    let res = svc::app(st).oneshot(req).await.unwrap();
    let status = res.status();
    let bytes = res.into_body().collect().await.unwrap().to_bytes().to_vec();
    (status, bytes)
}

fn token(roles: &[&str]) -> String {
    svc::AppState::for_tests().auth.issue("tester", roles, 60).unwrap()
}

'''

TESTS = '''
#[tokio::test]
async fn {name}_status() {{
    wire_everything().await;
    let (status, _) = call(Request::get("/health").body(Body::empty()).unwrap()).await;
    assert_eq!(status, StatusCode::OK, "{name}");
}}

#[tokio::test]
async fn {name}_publish() {{
    wire_everything().await;
    let body = serde_json::json!({{ "topic": "{name}.events", "body": {{ "case": "{name}", "n": {n} }} }});
    let req = Request::post("/publish")
        .header("content-type", "application/json")
        .header("authorization", format!("Bearer {{}}", token(&["publisher"])))
        .body(Body::from(body.to_string()))
        .unwrap();
    let (status, bytes) = call(req).await;
    assert_eq!(status, StatusCode::ACCEPTED, "{{}}", String::from_utf8_lossy(&bytes));
}}

#[test]
fn {name}_core() {{
    let n = svc_core::Notification::new("{name}", serde_json::json!({{ "n": {n} }})).unwrap();
    assert_eq!(svc_core::Notification::from_bytes(&n.to_bytes().unwrap()).unwrap(), n);
}}
'''


def body(name: str, n: int) -> str:
    return (textwrap.dedent(HELPERS).lstrip() + textwrap.dedent(TESTS).format(name=name, n=n))


def generate(crate_dir: pathlib.Path, layout: str) -> None:
    tests = crate_dir / "tests"
    if tests.exists():
        shutil.rmtree(tests)
    tests.mkdir()
    manifest = crate_dir / "Cargo.toml"
    text = manifest.read_text()
    marker = "\n# --- generated test layout ---\n"
    text = text.split(marker)[0]

    if layout == "split":
        for i, name in enumerate(NAMES, 1):
            (tests / f"t{i:02d}_{name}.rs").write_text(body(name, i))
    elif layout == "single":
        it = tests / "it"
        it.mkdir()
        mods = []
        for i, name in enumerate(NAMES, 1):
            mod = f"t{i:02d}_{name}"
            mods.append(f"mod {mod};")
            (it / f"{mod}.rs").write_text(body(name, i))
        (it / "main.rs").write_text("//! All integration tests in one binary.\n\n" + "\n".join(mods) + "\n")
        text += marker + '[[test]]\nname = "it"\npath = "tests/it/main.rs"\n'
        # autotests = false would also work; an explicit [[test]] with only
        # tests/it/ present is enough because there are no top-level tests/*.rs.
    else:
        sys.exit(f"unknown layout {layout}")
    manifest.write_text(text)


if __name__ == "__main__":
    generate(pathlib.Path(sys.argv[1]), sys.argv[2])
    print(f"generated {sys.argv[2]} layout in {sys.argv[1]}/tests")
