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


#[tokio::test]
async fn jwt_wrong_secret_status() {
    wire_everything().await;
    let (status, _) = call(Request::get("/health").body(Body::empty()).unwrap()).await;
    assert_eq!(status, StatusCode::OK, "jwt_wrong_secret");
}

#[tokio::test]
async fn jwt_wrong_secret_publish() {
    wire_everything().await;
    let body = serde_json::json!({ "topic": "jwt_wrong_secret.events", "body": { "case": "jwt_wrong_secret", "n": 12 } });
    let req = Request::post("/publish")
        .header("content-type", "application/json")
        .header("authorization", format!("Bearer {}", token(&["publisher"])))
        .body(Body::from(body.to_string()))
        .unwrap();
    let (status, bytes) = call(req).await;
    assert_eq!(status, StatusCode::ACCEPTED, "{}", String::from_utf8_lossy(&bytes));
}

#[test]
fn jwt_wrong_secret_core() {
    let n = svc_core::Notification::new("jwt_wrong_secret", serde_json::json!({ "n": 12 })).unwrap();
    assert_eq!(svc_core::Notification::from_bytes(&n.to_bytes().unwrap()).unwrap(), n);
}
