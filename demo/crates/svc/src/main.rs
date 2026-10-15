use clap::Parser;
use std::sync::Arc;

#[derive(Parser)]
struct Args {
    #[arg(long, env = "LISTEN", default_value = "127.0.0.1:8080")]
    listen: String,
    #[arg(long, env = "NATS_URL")]
    nats: Option<String>,
    #[arg(long, env = "OTLP_ENDPOINT")]
    otlp: Option<String>,
    #[arg(long, env = "JWT_SECRET", default_value = "dev-secret-dev-secret-dev-secret")]
    secret: String,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let args = Args::parse();
    let _provider = svc::telemetry::init(args.otlp.as_deref())?;
    let nats = match &args.nats {
        Some(u) => Some(svc::connect_nats(u).await?),
        None => None,
    };
    let state = svc::AppState {
        auth: Arc::new(svc_core::Auth::hs256(args.secret.as_bytes())),
        nats,
        http: reqwest::Client::new(),
        upstream: None,
    };
    let listener = tokio::net::TcpListener::bind(&args.listen).await?;
    axum::serve(listener, svc::app(state)).await?;
    Ok(())
}
