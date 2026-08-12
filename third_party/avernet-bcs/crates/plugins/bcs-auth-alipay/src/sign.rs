//! Alipay RSA2 (SHA256WithRSA) request signing and response verification.
//!
//! Alipay requires every gateway API request to carry an `RSA2` signature.
//! This module handles:
//! - **Signing**: Build the canonical string from sorted parameters, sign it
//!   with the application's RSA private key, and Base64-encode the result.
//! - **Verification**: Verify the `sign` field on gateway responses using the
//!   Alipay RSA public key. Verification failure is logged as a warning but
//!   does not block the request (fail-open for operational flexibility).

use aws_lc_rs::rand::SystemRandom;
use aws_lc_rs::signature::{
    RSA_PKCS1_2048_8192_SHA256, RSA_PKCS1_SHA256, RsaKeyPair, RsaSubjectPublicKey,
    UnparsedPublicKey,
};
use base64::{Engine, engine::general_purpose::STANDARD as BASE64};

/// Parsed Alipay RSA private key backed by AWS-LC.
pub struct AlipayPrivateKey(RsaKeyPair);

/// Canonical RFC 8017 public-key bytes used for AWS-LC verification.
pub struct AlipayPublicKey(Vec<u8>);

/// Error type for signing and verification operations.
#[derive(Debug, thiserror::Error)]
pub enum AlipaySignError {
    #[error("invalid private key PEM: {0}")]
    InvalidPrivateKey(String),
    #[error("invalid public key PEM: {0}")]
    InvalidPublicKey(String),
    #[error("signing failed: {0}")]
    SignFailed(String),
    #[error("verification failed: {0}")]
    VerifyFailed(String),
}

/// Parse an RSA private key from PEM text. Tries PKCS#8 first, then PKCS#1.
pub fn parse_private_key(pem_text: &str) -> Result<AlipayPrivateKey, AlipaySignError> {
    let pem = pem::parse(pem_text)
        .map_err(|error| AlipaySignError::InvalidPrivateKey(error.to_string()))?;
    let key = match pem.tag() {
        "PRIVATE KEY" => RsaKeyPair::from_pkcs8(pem.contents()),
        "RSA PRIVATE KEY" => RsaKeyPair::from_der(pem.contents()),
        tag => {
            return Err(AlipaySignError::InvalidPrivateKey(format!(
                "unsupported PEM label {tag}"
            )));
        }
    }
    .map_err(|error| AlipaySignError::InvalidPrivateKey(error.to_string()))?;
    Ok(AlipayPrivateKey(key))
}

/// Parse an RSA public key from PEM text.
pub fn parse_public_key(pem_text: &str) -> Result<AlipayPublicKey, AlipaySignError> {
    let pem = pem::parse(pem_text)
        .map_err(|error| AlipaySignError::InvalidPublicKey(error.to_string()))?;
    if !matches!(pem.tag(), "PUBLIC KEY" | "RSA PUBLIC KEY") {
        return Err(AlipaySignError::InvalidPublicKey(format!(
            "unsupported PEM label {}",
            pem.tag()
        )));
    }
    let key = RsaSubjectPublicKey::from_der(pem.contents())
        .map_err(|error| AlipaySignError::InvalidPublicKey(error.to_string()))?;
    Ok(AlipayPublicKey(key.as_ref().to_vec()))
}

/// Build the canonical signing string from sorted parameters.
///
/// Excludes `sign` and `sign_type`. Parameters are sorted by key (using
/// BTreeMap ensures this). Values are NOT URL-encoded per Alipay spec.
pub fn build_sign_string(params: &std::collections::BTreeMap<String, String>) -> String {
    params
        .iter()
        .filter(|(k, _)| k != &"sign" && k != &"sign_type")
        .filter(|(_, v)| !v.is_empty())
        .map(|(k, v)| format!("{k}={v}"))
        .collect::<Vec<_>>()
        .join("&")
}

/// Sign parameters using RSA2 (SHA256WithRSA) and return the Base64-encoded signature.
pub fn sign_params(
    params: &std::collections::BTreeMap<String, String>,
    private_key: &AlipayPrivateKey,
) -> Result<String, AlipaySignError> {
    let sign_string = build_sign_string(params);
    let mut signature = vec![0; private_key.0.public_modulus_len()];
    private_key
        .0
        .sign(
            &RSA_PKCS1_SHA256,
            &SystemRandom::new(),
            sign_string.as_bytes(),
            &mut signature,
        )
        .map_err(|error| AlipaySignError::SignFailed(error.to_string()))?;
    Ok(BASE64.encode(signature))
}

/// Verify a response signature against the Alipay public key using sorted
/// parameter reconstruction. Used in unit tests for sign/verify roundtrip.
pub fn verify_sign(
    params: &std::collections::BTreeMap<String, String>,
    sign: &str,
    public_key: &AlipayPublicKey,
) -> Result<(), AlipaySignError> {
    let sign_string = build_sign_string(params);
    verify_raw(sign_string.as_bytes(), sign, public_key)
}

/// Verify a signature against raw bytes. Used for response verification where
/// the signed content is the raw JSON substring (not reconstructed params).
pub fn verify_raw(
    content: &[u8],
    sign: &str,
    public_key: &AlipayPublicKey,
) -> Result<(), AlipaySignError> {
    let signature_bytes = BASE64
        .decode(sign)
        .map_err(|e| AlipaySignError::VerifyFailed(format!("base64 decode: {e}")))?;
    UnparsedPublicKey::new(&RSA_PKCS1_2048_8192_SHA256, &public_key.0)
        .verify(content, &signature_bytes)
        .map_err(|error| AlipaySignError::VerifyFailed(error.to_string()))
}

#[cfg(test)]
mod tests {
    use aws_lc_rs::signature::KeyPair as _;

    use super::*;

    fn generate_test_keypair() -> (AlipayPrivateKey, AlipayPublicKey) {
        let private_key = RsaKeyPair::generate(aws_lc_rs::rsa::KeySize::Rsa2048)
            .expect("failed to generate test RSA key");
        let public_key = AlipayPublicKey(private_key.public_key().as_ref().to_vec());
        (AlipayPrivateKey(private_key), public_key)
    }

    #[test]
    fn build_sign_string_excludes_sign_and_sign_type() {
        let mut params = std::collections::BTreeMap::new();
        params.insert("app_id".to_string(), "2021001".to_string());
        params.insert("method".to_string(), "alipay.test".to_string());
        params.insert("sign".to_string(), "existing-signature".to_string());
        params.insert("sign_type".to_string(), "RSA2".to_string());
        params.insert("charset".to_string(), "utf-8".to_string());

        let result = build_sign_string(&params);
        // BTreeMap sorts keys alphabetically: app_id, charset, method
        assert_eq!(result, "app_id=2021001&charset=utf-8&method=alipay.test");
        assert!(!result.contains("sign"));
        assert!(!result.contains("sign_type"));
    }

    #[test]
    fn build_sign_string_excludes_empty_values() {
        let mut params = std::collections::BTreeMap::new();
        params.insert("app_id".to_string(), "2021001".to_string());
        params.insert("biz_content".to_string(), String::new());

        let result = build_sign_string(&params);
        assert_eq!(result, "app_id=2021001");
        assert!(!result.contains("biz_content"));
    }

    #[test]
    fn sign_and_verify_roundtrip() {
        let (private_key, public_key) = generate_test_keypair();

        let mut params = std::collections::BTreeMap::new();
        params.insert("app_id".to_string(), "2021001234567890".to_string());
        params.insert(
            "method".to_string(),
            "alipay.system.oauth.token".to_string(),
        );
        params.insert("charset".to_string(), "utf-8".to_string());

        let signature = sign_params(&params, &private_key).expect("signing should succeed");
        assert!(!signature.is_empty());

        let result = verify_sign(&params, &signature, &public_key);
        assert!(
            result.is_ok(),
            "signature verification should succeed: {:?}",
            result
        );
    }

    #[test]
    fn verify_fails_with_wrong_key() {
        let (private_key, _public_key) = generate_test_keypair();
        let (_, wrong_public_key) = generate_test_keypair();

        let mut params = std::collections::BTreeMap::new();
        params.insert("app_id".to_string(), "2021001234567890".to_string());
        params.insert(
            "method".to_string(),
            "alipay.system.oauth.token".to_string(),
        );

        let signature = sign_params(&params, &private_key).expect("signing should succeed");
        let result = verify_sign(&params, &signature, &wrong_public_key);
        assert!(result.is_err(), "verification with wrong key should fail");
    }

    #[test]
    fn verify_fails_with_tampered_params() {
        let (private_key, public_key) = generate_test_keypair();

        let mut params = std::collections::BTreeMap::new();
        params.insert("app_id".to_string(), "2021001234567890".to_string());
        params.insert(
            "method".to_string(),
            "alipay.system.oauth.token".to_string(),
        );

        let signature = sign_params(&params, &private_key).expect("signing should succeed");

        // Tamper with params
        params.insert("app_id".to_string(), "TAMPERED_ID".to_string());
        let result = verify_sign(&params, &signature, &public_key);
        assert!(
            result.is_err(),
            "verification with tampered params should fail"
        );
    }
}
