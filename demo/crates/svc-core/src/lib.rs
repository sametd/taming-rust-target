//! Domain types and auth for the demo service.

use chrono::{DateTime, Utc};
use jsonwebtoken::{Algorithm, DecodingKey, EncodingKey, Header, Validation, decode, encode};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Debug, thiserror::Error)]
pub enum CoreError {
    #[error("invalid token: {0}")]
    Token(#[from] jsonwebtoken::errors::Error),
    #[error("invalid payload: {0}")]
    Payload(#[from] serde_json::Error),
    #[error("validation failed: {0}")]
    Validation(String),
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Notification {
    pub id: Uuid,
    pub topic: String,
    pub body: serde_json::Value,
    pub created_at: DateTime<Utc>,
}

impl Notification {
    pub fn new(topic: impl Into<String>, body: serde_json::Value) -> Result<Self, CoreError> {
        let topic = topic.into();
        if topic.is_empty() || topic.len() > 128 || topic.contains(char::is_whitespace) {
            return Err(CoreError::Validation(format!("bad topic {topic:?}")));
        }
        Ok(Self { id: Uuid::new_v4(), topic, body, created_at: Utc::now() })
    }

    pub fn to_bytes(&self) -> Result<Vec<u8>, CoreError> {
        Ok(serde_json::to_vec(self)?)
    }

    pub fn from_bytes(b: &[u8]) -> Result<Self, CoreError> {
        Ok(serde_json::from_slice(b)?)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Claims {
    pub sub: String,
    pub roles: Vec<String>,
    pub exp: usize,
}

pub struct Auth {
    enc: EncodingKey,
    dec: DecodingKey,
    validation: Validation,
}

impl Auth {
    pub fn hs256(secret: &[u8]) -> Self {
        let mut validation = Validation::new(Algorithm::HS256);
        validation.leeway = 5;
        Self { enc: EncodingKey::from_secret(secret), dec: DecodingKey::from_secret(secret), validation }
    }

    pub fn issue(&self, sub: &str, roles: &[&str], ttl_secs: i64) -> Result<String, CoreError> {
        let exp = (Utc::now().timestamp() + ttl_secs) as usize;
        let claims = Claims { sub: sub.into(), roles: roles.iter().map(|r| r.to_string()).collect(), exp };
        Ok(encode(&Header::new(Algorithm::HS256), &claims, &self.enc)?)
    }

    pub fn verify(&self, token: &str) -> Result<Claims, CoreError> {
        Ok(decode::<Claims>(token, &self.dec, &self.validation)?.claims)
    }
}

/// Used by the `backtrace` example to check that file:line survives each debuginfo setting.
#[inline(never)]
pub fn explode(depth: u32) -> u32 {
    if depth == 0 {
        panic!("boom from svc-core");
    }
    explode(depth - 1) + 1
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn topic_validation() {
        assert!(Notification::new("", serde_json::Value::Null).is_err());
        assert!(Notification::new("a b", serde_json::Value::Null).is_err());
        assert!(Notification::new("ok.topic", serde_json::Value::Null).is_ok());
    }

    #[test]
    fn jwt_roundtrip() {
        let a = Auth::hs256(b"0123456789abcdef0123456789abcdef");
        let t = a.issue("me", &["publisher"], 60).unwrap();
        assert_eq!(a.verify(&t).unwrap().sub, "me");
    }
}
