//! Unit tests for the Alipay OAuth provider.

use bcs_auth_alipay::sign;
use bcs_auth_alipay::{AlipayConfig, AlipayOAuthProvider};
use bcs_auth_api::OAuthProvider;

fn test_keys() -> (String, String) {
    use aws_lc_rs::encoding::{AsDer, Pkcs8V1Der, PublicKeyX509Der};
    use aws_lc_rs::signature::{KeyPair as _, RsaKeyPair};

    let private_key =
        RsaKeyPair::generate(aws_lc_rs::rsa::KeySize::Rsa2048).expect("generate RSA key");
    let private_der =
        AsDer::<Pkcs8V1Der<'static>>::as_der(&private_key).expect("encode private key");
    let public_der = AsDer::<PublicKeyX509Der<'static>>::as_der(private_key.public_key())
        .expect("encode public key");
    let private_pem = pem::encode(&pem::Pem::new("PRIVATE KEY", private_der.as_ref()));
    let public_pem = pem::encode(&pem::Pem::new("PUBLIC KEY", public_der.as_ref()));
    (private_pem, public_pem)
}

fn test_config() -> AlipayConfig {
    let (private_pem, public_pem) = test_keys();
    AlipayConfig {
        app_id: "2021001234567890".to_string(),
        private_key_pem: private_pem,
        alipay_public_key_pem: public_pem,
    }
}

#[test]
fn alipay_provider_name() {
    let provider = AlipayOAuthProvider::new(test_config()).expect("create provider");
    assert_eq!(provider.name(), "alipay");
}

#[test]
fn alipay_auth_url_format() {
    let provider = AlipayOAuthProvider::new(test_config()).expect("create provider");
    let url = provider.auth_url(
        "csrf-state-xyz",
        "http://localhost:21000/auth/callback/alipay",
    );

    assert!(url.starts_with("https://openauth.alipay.com/oauth2/publicAppAuthorize.htm"));
    assert!(url.contains("app_id=2021001234567890"));
    assert!(url.contains("state=csrf-state-xyz"));
    assert!(url.contains("redirect_uri="));
    assert!(url.contains("scope=auth_user"));
}

#[test]
fn alipay_auth_url_contains_state() {
    let provider = AlipayOAuthProvider::new(test_config()).expect("create provider");
    let url = provider.auth_url("my-state-456", "https://example.com/callback/alipay");
    assert!(url.contains("state=my-state-456"));
}

/// Rule 25: the Alipay provider satisfies the shared offline `OAuthProvider`
/// contract that the mock and every other provider also pass.
#[test]
fn alipay_provider_passes_offline_contract() {
    let provider = AlipayOAuthProvider::new(test_config()).expect("create provider");
    bcs_test_support::run_oauth_provider_offline_contract(&provider);
}

#[test]
fn alipay_provider_rejects_invalid_private_key() {
    let config = AlipayConfig {
        app_id: "2021001234567890".to_string(),
        private_key_pem: "not-a-valid-pem".to_string(),
        alipay_public_key_pem: "not-a-valid-pem".to_string(),
    };
    let result = AlipayOAuthProvider::new(config);
    assert!(result.is_err(), "should reject invalid PEM keys");
}

// --- sign module tests (additional to inline tests) ---

#[test]
fn sign_build_string_ordering() {
    let mut params = std::collections::BTreeMap::new();
    params.insert("zebra".to_string(), "z".to_string());
    params.insert("alpha".to_string(), "a".to_string());
    params.insert("middle".to_string(), "m".to_string());

    let result = sign::build_sign_string(&params);
    assert_eq!(result, "alpha=a&middle=m&zebra=z");
}
