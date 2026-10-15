use utoipa::OpenApi;
fn main() {
    println!("{}", svc::ApiDoc::openapi().to_pretty_json().unwrap());
}
