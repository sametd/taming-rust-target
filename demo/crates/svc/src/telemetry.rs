use opentelemetry::trace::TracerProvider as _;
use opentelemetry_otlp::WithExportConfig;
use opentelemetry_sdk::trace::SdkTracerProvider;
use tracing_subscriber::{EnvFilter, layer::SubscriberExt, util::SubscriberInitExt};

/// Builds the OTLP pipeline. Called from main and from every test, so the
/// whole tonic/prost/OTel stack is linked into each test binary, as in real services.
pub fn tracer_provider(endpoint: &str) -> anyhow::Result<SdkTracerProvider> {
    let exporter = opentelemetry_otlp::SpanExporter::builder()
        .with_tonic()
        .with_endpoint(endpoint)
        .build()?;
    Ok(SdkTracerProvider::builder().with_batch_exporter(exporter).build())
}

pub fn init(endpoint: Option<&str>) -> anyhow::Result<Option<SdkTracerProvider>> {
    let provider = endpoint.map(tracer_provider).transpose()?;
    let otel = provider.as_ref().map(|p| tracing_opentelemetry::layer().with_tracer(p.tracer("svc")));
    let _ = tracing_subscriber::registry()
        .with(EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()))
        .with(tracing_subscriber::fmt::layer().json())
        .with(otel)
        .try_init();
    Ok(provider)
}
