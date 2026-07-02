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
//! 3. [`generate_urlsafe_token`] — URL-safe no-padding base64 over CSPRNG bytes,
//!    matching Python's `secrets.token_urlsafe(n)` shape for invitation tokens.
//! 4. [`generate_device_user_code`] — the 8-character RFC-8628-style user code
//!    alphabet Python uses for CLI device login (`ABCDEFGHJKLMNPQRSTUVWXYZ23456789`).
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
/// Python `_USER_CODE_ALPHABET`: excludes I/O/0/1 to avoid transcription ambiguity.
pub const DEVICE_USER_CODE_ALPHABET: &str = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
/// Python `_USER_CODE_LEN`.
pub const DEVICE_USER_CODE_LEN: usize = 8;

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

/// Generate a URL-safe, no-padding token from `num_bytes` random bytes. This is
/// shape-compatible with Python `secrets.token_urlsafe(num_bytes)` and is used
/// by the P2 invitation flow for bearer links that must fit safely in URLs.
pub fn generate_urlsafe_token(num_bytes: usize) -> String {
    let mut bytes = vec![0u8; num_bytes];
    getrandom::getrandom(&mut bytes).expect("OS CSPRNG must be available to mint tokens");
    base64_urlsafe_no_pad(&bytes)
}

/// Mint an 8-character device-login user code using Python's ambiguity-free
/// alphabet. The alphabet has exactly 32 symbols, so `byte & 31` maps CSPRNG
/// bytes without modulo bias.
pub fn generate_device_user_code() -> String {
    let alphabet = DEVICE_USER_CODE_ALPHABET.as_bytes();
    debug_assert_eq!(alphabet.len(), 32);
    let mut bytes = [0u8; DEVICE_USER_CODE_LEN];
    getrandom::getrandom(&mut bytes).expect("OS CSPRNG must be available to mint device codes");
    let mut out = String::with_capacity(DEVICE_USER_CODE_LEN);
    for byte in bytes {
        out.push(alphabet[(byte & 31) as usize] as char);
    }
    out
}

fn base64_urlsafe_no_pad(bytes: &[u8]) -> String {
    const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    let mut out = String::with_capacity((bytes.len() * 4).div_ceil(3));
    for chunk in bytes.chunks(3) {
        let b0 = chunk[0];
        let b1 = *chunk.get(1).unwrap_or(&0);
        let b2 = *chunk.get(2).unwrap_or(&0);
        let n = ((b0 as u32) << 16) | ((b1 as u32) << 8) | b2 as u32;
        out.push(ALPHABET[((n >> 18) & 0x3f) as usize] as char);
        out.push(ALPHABET[((n >> 12) & 0x3f) as usize] as char);
        if chunk.len() > 1 {
            out.push(ALPHABET[((n >> 6) & 0x3f) as usize] as char);
        }
        if chunk.len() > 2 {
            out.push(ALPHABET[(n & 0x3f) as usize] as char);
        }
    }
    out
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
    const USERPASSWORD_HASH: &str = "$2b$12$7zqrguT7EVNDjaBFQ03ITe6Q5Y1YiOL6Vu45Q6rjaLF3VfNYU/VD6";
    const ADMINPASSWORD_HASH: &str = "$2b$12$CaGi/tOMpl3fjcABfzRrZuE36GNKdszg.85vTcs7F9SGNgOj8/VwC";

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
        assert!(hex
            .chars()
            .all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase()));
        // Two mints differ (CSPRNG, not constant).
        assert_ne!(generate_api_key(), generate_api_key());
    }

    #[test]
    fn urlsafe_token_matches_python_shape() {
        assert_eq!(base64_urlsafe_no_pad(&[0]), "AA");
        assert_eq!(base64_urlsafe_no_pad(&[0, 0]), "AAA");
        assert_eq!(base64_urlsafe_no_pad(&[0, 0, 0]), "AAAA");
        assert_eq!(base64_urlsafe_no_pad(b"hello"), "aGVsbG8");

        let token = generate_urlsafe_token(32);
        // Python `secrets.token_urlsafe(32)` produces ceil(32*4/3)=43 chars
        // without `=` padding.
        assert_eq!(token.len(), 43);
        assert!(token
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_'));
        assert_ne!(token, generate_urlsafe_token(32));
    }

    #[test]
    fn device_user_code_matches_python_shape() {
        let code = generate_device_user_code();
        assert_eq!(code.len(), DEVICE_USER_CODE_LEN);
        assert!(code.chars().all(|c| DEVICE_USER_CODE_ALPHABET.contains(c)));
        assert!(!code.chars().any(|c| matches!(c, 'I' | 'O' | '0' | '1')));
        assert_ne!(code, generate_device_user_code());
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
        assert!(id
            .chars()
            .all(|c| c == '-' || (c.is_ascii_hexdigit() && !c.is_ascii_uppercase())));
        assert_ne!(generate_uuid_v4(), generate_uuid_v4());
    }
}
