//! `agistack-adapters-secrets`: the server-tier credential primitives for the
//! **P2 identity vertical** (plan.md Section 15.2).
//!
//! The Python login path (`routers/auth.py::login_for_access_token` ->
//! `AuthService`, `src/application/services/auth_service_v2.py`) does two secret
//! operations this crate mirrors byte-for-byte so a request served by Rust is
//! indistinguishable from one served by Python:
//!
//! 1. [`verify_password`] — `bcrypt.checkpw(plain, hashed)`. The Rust `bcrypt`
//!    crate reads the same `$2b$`/`$2a$` modular-crypt hashes `passlib`/`bcrypt`
//!    write, so a password hash produced by Python verifies here unchanged. Like
//!    Python, a malformed stored hash yields `false` (never a panic).
//! 2. [`generate_api_key`] — `ms_sk_` + `hex(32 random bytes)` from the OS CSPRNG,
//!    identical in shape to Python's `f"ms_sk_{secrets.token_bytes(32).hex()}"`.
//!    The raw key is returned once; the caller stores only its SHA-256 (done in
//!    `adapters-postgres`), exactly as Python does.
//!
//! ## Agent First
//! Nothing here is a *judgment*: bcrypt verification is a deterministic
//! cryptographic check and key generation is CSPRNG bytes + hex encoding. These
//! are protocol/arithmetic facts, explicitly outside the agent-decision boundary.

/// Verify a plaintext password against a stored bcrypt hash, byte-compatible with
/// the Python `AuthService.verify_password` (`bcrypt.checkpw`).
///
/// Returns `false` for a non-matching password **and** for a malformed/empty
/// stored hash — mirroring the Python `try/except -> False` behavior so a corrupt
/// row can never 500 the login path.
pub fn verify_password(plain_password: &str, hashed_password: &str) -> bool {
    bcrypt::verify(plain_password, hashed_password).unwrap_or(false)
}

/// Hash a password with bcrypt at the same default cost (12) Python uses
/// (`bcrypt.gensalt()` default). Not needed by the login *verify* path, but used
/// by integration tests to seed a Python-shaped `users` row, and available for a
/// future Rust-owned user-creation endpoint.
pub fn hash_password(plain_password: &str) -> Result<String, SecretError> {
    bcrypt::hash(plain_password, 12).map_err(|e| SecretError(e.to_string()))
}

/// The `ms_sk_` prefix every MemStack API key carries (Python
/// `AuthService.generate_api_key`).
pub const API_KEY_PREFIX: &str = "ms_sk_";

/// Mint a fresh API key: `ms_sk_` + 64 lowercase hex chars from 32 CSPRNG bytes.
/// Shape-identical to Python `f"ms_sk_{secrets.token_bytes(32).hex()}"`. The
/// returned value is the *plaintext* key shown to the caller exactly once.
pub fn generate_api_key() -> String {
    let mut bytes = [0u8; 32];
    // OS CSPRNG. `getrandom` is the same primitive class as CPython's `secrets`.
    getrandom::getrandom(&mut bytes).expect("OS CSPRNG must be available to mint API keys");
    let mut key = String::with_capacity(API_KEY_PREFIX.len() + 64);
    key.push_str(API_KEY_PREFIX);
    for byte in bytes {
        // Lowercase hex, two chars per byte — identical to Python `bytes.hex()`.
        key.push(char::from_digit((byte >> 4) as u32, 16).unwrap());
        key.push(char::from_digit((byte & 0x0f) as u32, 16).unwrap());
    }
    key
}

/// Generate a random RFC 4122 **v4** UUID as a lowercase, hyphenated string —
/// mirroring Python's `str(uuid4())` used for ids like `api_keys.id`. Kept
/// dependency-free (16 CSPRNG bytes with the version/variant bits set) so the
/// crate stays a thin credential-primitives layer.
pub fn generate_uuid_v4() -> String {
    let mut b = [0u8; 16];
    getrandom::getrandom(&mut b).expect("OS CSPRNG must be available to mint ids");
    b[6] = (b[6] & 0x0f) | 0x40; // version 4
    b[8] = (b[8] & 0x3f) | 0x80; // RFC 4122 variant (10xx)
    let mut s = String::with_capacity(36);
    for (i, byte) in b.iter().enumerate() {
        if matches!(i, 4 | 6 | 8 | 10) {
            s.push('-');
        }
        s.push(char::from_digit((byte >> 4) as u32, 16).unwrap());
        s.push(char::from_digit((byte & 0x0f) as u32, 16).unwrap());
    }
    s
}

/// A minimal opaque error for the (rare) hashing failure path.
#[derive(Debug)]
pub struct SecretError(pub String);

impl std::fmt::Display for SecretError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "secret error: {}", self.0)
    }
}

impl std::error::Error for SecretError {}

#[cfg(test)]
mod unit {
    use super::*;

    // Real `$2b$12$` hashes produced by Python `bcrypt.hashpw(pw, gensalt())`
    // for the platform's seeded credentials. Because a bcrypt hash embeds its
    // salt, these are permanent vectors: the Rust `bcrypt` crate verifying them
    // proves it reads Python's output byte-for-byte.
    const USERPASSWORD_HASH: &str =
        "$2b$12$7zqrguT7EVNDjaBFQ03ITe6Q5Y1YiOL6Vu45Q6rjaLF3VfNYU/VD6";
    const ADMINPASSWORD_HASH: &str =
        "$2b$12$CaGi/tOMpl3fjcABfzRrZuE36GNKdszg.85vTcs7F9SGNgOj8/VwC";

    #[test]
    fn verifies_python_generated_bcrypt_hashes() {
        // Correct passwords verify against Python-produced `$2b$` hashes.
        assert!(verify_password("userpassword", USERPASSWORD_HASH));
        assert!(verify_password("adminpassword", ADMINPASSWORD_HASH));
        // Wrong passwords are rejected.
        assert!(!verify_password("wrong", USERPASSWORD_HASH));
        assert!(!verify_password("adminpassword", USERPASSWORD_HASH));
    }

    #[test]
    fn malformed_hash_is_false_not_panic() {
        // Python's verify_password catches and returns False; so do we.
        assert!(!verify_password("anything", ""));
        assert!(!verify_password("anything", "not-a-bcrypt-hash"));
    }

    #[test]
    fn round_trips_our_own_hash() {
        let h = hash_password("s3cret!").unwrap();
        assert!(h.starts_with("$2b$12$"));
        assert!(verify_password("s3cret!", &h));
        assert!(!verify_password("s3cret", &h));
    }

    #[test]
    fn generated_key_has_ms_sk_shape() {
        let k = generate_api_key();
        assert!(k.starts_with("ms_sk_"));
        // ms_sk_ (6) + 64 hex chars.
        assert_eq!(k.len(), 6 + 64);
        let hex = &k[6..];
        assert!(hex.chars().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase()));
        // Two mints differ (CSPRNG, not constant).
        assert_ne!(generate_api_key(), generate_api_key());
    }

    #[test]
    fn generated_uuid_is_v4_shaped() {
        let id = generate_uuid_v4();
        // 8-4-4-4-12 hyphenated, 36 chars total.
        assert_eq!(id.len(), 36);
        let parts: Vec<&str> = id.split('-').collect();
        assert_eq!(
            parts.iter().map(|p| p.len()).collect::<Vec<_>>(),
            vec![8, 4, 4, 4, 12]
        );
        // Version nibble is 4; variant nibble is one of 8/9/a/b.
        assert_eq!(&parts[2][..1], "4");
        assert!(matches!(&parts[3][..1], "8" | "9" | "a" | "b"));
        assert!(id.chars().all(|c| c == '-' || (c.is_ascii_hexdigit() && !c.is_ascii_uppercase())));
        assert_ne!(generate_uuid_v4(), generate_uuid_v4());
    }
}
