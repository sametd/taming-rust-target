//! A small but fully wired service: axum + JWT + NATS + OTLP tracing + upstream HTTP.
//! Every integration test calls `app()`, so every test binary links the same
//! amount of dependency code a real service would.

use std::{sync::Arc, time::Duration};

use axum::{
    Json, Router,
    extract::{Path, State},
    http::{HeaderMap, StatusCode},
    routing::{get, post},
};
use serde::{Deserialize, Serialize};
use svc_core::{Auth, Notification};
use tower_http::{compression::CompressionLayer, cors::CorsLayer, timeout::TimeoutLayer, trace::TraceLayer};
use utoipa::OpenApi;

pub mod telemetry;

#[derive(Clone)]
pub struct AppState {
    pub auth: Arc<Auth>,
    pub nats: Option<async_nats::Client>,
    pub http: reqwest::Client,
    pub upstream: Option<String>,
}

impl AppState {
    pub fn for_tests() -> Self {
        Self {
            auth: Arc::new(Auth::hs256(b"test-secret-test-secret-test-secret")),
            nats: None,
            http: reqwest::Client::builder().timeout(Duration::from_secs(2)).build().expect("client"),
            upstream: None,
        }
    }
}

#[derive(Serialize, Deserialize, utoipa::ToSchema)]
pub struct PublishRequest {
    pub topic: String,
    pub body: serde_json::Value,
}

#[derive(Serialize, Deserialize, utoipa::ToSchema)]
pub struct PublishResponse {
    pub id: String,
    pub delivered: bool,
}

#[derive(OpenApi)]
#[openapi(paths(health, publish), components(schemas(PublishRequest, PublishResponse)))]
pub struct ApiDoc;

#[utoipa::path(get, path = "/health", responses((status = 200, description = "ok")))]
pub async fn health() -> &'static str {
    "ok"
}

#[utoipa::path(post, path = "/publish", request_body = PublishRequest,
    responses((status = 202, body = PublishResponse), (status = 401), (status = 400)))]
pub async fn publish(
    State(st): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<PublishRequest>,
) -> Result<(StatusCode, Json<PublishResponse>), (StatusCode, String)> {
    let token = headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.strip_prefix("Bearer "))
        .ok_or((StatusCode::UNAUTHORIZED, "missing token".into()))?;
    let claims = st.auth.verify(token).map_err(|e| (StatusCode::UNAUTHORIZED, e.to_string()))?;
    if !claims.roles.iter().any(|r| r == "publisher") {
        return Err((StatusCode::FORBIDDEN, "not a publisher".into()));
    }
    let n = Notification::new(req.topic, req.body).map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))?;
    let mut delivered = false;
    if let Some(nats) = &st.nats {
        let bytes = n.to_bytes().map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
        nats.publish(n.topic.clone(), bytes.into())
            .await
            .map_err(|e| (StatusCode::BAD_GATEWAY, e.to_string()))?;
        delivered = true;
    }
    if let Some(up) = &st.upstream {
        let _ = st.http.post(up).json(&n).send().await;
    }
    tracing::info!(id = %n.id, topic = %n.topic, delivered, "published");
    Ok((StatusCode::ACCEPTED, Json(PublishResponse { id: n.id.to_string(), delivered })))
}

pub async fn get_topic(Path(topic): Path<String>) -> Json<serde_json::Value> {
    Json(serde_json::json!({ "topic": topic, "subscribers": 0 }))
}

pub fn app(state: AppState) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/publish", post(publish))
        .route("/topics/{topic}", get(get_topic))
        .route("/openapi.json", get(|| async { Json(ApiDoc::openapi()) }))
        .layer(TraceLayer::new_for_http())
        .layer(CompressionLayer::new())
        .layer(CorsLayer::permissive())
        .layer(TimeoutLayer::with_status_code(StatusCode::REQUEST_TIMEOUT, Duration::from_secs(10)))
        .with_state(state)
}

pub async fn connect_nats(url: &str) -> anyhow::Result<async_nats::Client> {
    Ok(async_nats::ConnectOptions::new().name("svc").connect(url).await?)
}
