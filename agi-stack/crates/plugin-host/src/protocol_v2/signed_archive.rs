//! Native signed `.mspkg` verification. No extraction or executable loader is involved.
//!
//! The verified value cannot be constructed or deserialized by consumers. It owns immutable
//! artifact bytes and the exact signed manifest; copying its metadata is not a verification proof.
//! Provenance is a signature-covered reference, not a claim that its remote contents were audited.

mod validation;
pub use validation::bundle_manifest_digest_v2;

use super::{
    BundleManifestV2, BundleReferenceV2, DataPlaneTargetV2, PluginManifestV2, PluginModuleV2,
    RuntimeKindV2, TrustKindV2,
};
use base64::{engine::general_purpose::STANDARD, Engine as _};
use ring::signature::{UnparsedPublicKey, ED25519};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    io::{Cursor, Read},
    sync::Arc,
};

const MAX_ARCHIVE: usize = 64 * 1024 * 1024;
const MAX_FILES: usize = 512;
const MAX_UNCOMPRESSED: u64 = 128 * 1024 * 1024;
const MAX_DESCRIPTOR: usize = 2 * 1024 * 1024;

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
#[error("{code}: {message}")]
pub struct BundleArchiveV2Error {
    pub code: &'static str,
    pub message: &'static str,
}

fn reject(code: &'static str, message: &'static str) -> BundleArchiveV2Error {
    BundleArchiveV2Error { code, message }
}

/// Operator-supplied Ed25519 key, parsed from the standard RFC 8410 SPKI PEM encoding.
#[derive(Clone)]
pub struct TrustedEd25519KeyV2([u8; 32]);

impl TrustedEd25519KeyV2 {
    pub fn from_spki_pem(pem: &str) -> Result<Self, BundleArchiveV2Error> {
        let body = pem
            .trim()
            .strip_prefix("-----BEGIN PUBLIC KEY-----")
            .and_then(|value| value.strip_suffix("-----END PUBLIC KEY-----"))
            .ok_or_else(|| reject("bundle_signing_key_invalid", "expected public key PEM"))?;
        let encoded: String = body
            .chars()
            .filter(|value| !value.is_ascii_whitespace())
            .collect();
        let der = STANDARD
            .decode(encoded)
            .map_err(|_| reject("bundle_signing_key_invalid", "invalid public key base64"))?;
        // Ed25519 SubjectPublicKeyInfo has absent algorithm parameters and a 32-byte bit string.
        const PREFIX: &[u8] = &[
            0x30, 0x2a, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x03, 0x21, 0x00,
        ];
        let raw: [u8; 32] = der
            .strip_prefix(PREFIX)
            .and_then(|value| value.try_into().ok())
            .ok_or_else(|| reject("bundle_signing_key_invalid", "expected Ed25519 SPKI"))?;
        Ok(Self(raw))
    }
}

/// Immutable verification result. Deserialization cannot manufacture admission evidence.
///
/// ```compile_fail
/// use agistack_plugin_host::protocol_v2::signed_archive::VerifiedBundleArchiveV2;
/// let _: VerifiedBundleArchiveV2 = serde_json::from_str("{}").unwrap();
/// ```
#[derive(Clone)]
pub struct VerifiedBundleArchiveV2 {
    manifest: Arc<BundleManifestV2>,
    artifacts: Arc<BTreeMap<String, Vec<u8>>>,
    reference: BundleReferenceV2,
    approved_permissions: BTreeSet<String>,
}

/// Borrowed identity and bytes from an actual verified archive, never from renderer config.
pub struct VerifiedWasmArtifactV2<'a> {
    reference: &'a BundleReferenceV2,
    manifest: &'a PluginManifestV2,
    module: &'a PluginModuleV2,
    bytes: &'a [u8],
}

impl VerifiedWasmArtifactV2<'_> {
    pub fn reference(&self) -> &BundleReferenceV2 {
        self.reference
    }
    pub fn manifest(&self) -> &PluginManifestV2 {
        self.manifest
    }
    pub fn module(&self) -> &PluginModuleV2 {
        self.module
    }
    pub fn bytes(&self) -> &[u8] {
        self.bytes
    }
}

impl VerifiedBundleArchiveV2 {
    pub fn manifest(&self) -> &BundleManifestV2 {
        &self.manifest
    }
    pub fn reference(&self) -> &BundleReferenceV2 {
        &self.reference
    }
    pub fn approved_permissions(&self) -> &BTreeSet<String> {
        &self.approved_permissions
    }

    pub fn wasm_artifact(
        &self,
        plugin_id: &str,
        module_ref: &str,
        target: DataPlaneTargetV2,
    ) -> Result<VerifiedWasmArtifactV2<'_>, BundleArchiveV2Error> {
        let manifest = self
            .manifest
            .manifests
            .iter()
            .find(|item| item.plugin_id == plugin_id)
            .ok_or_else(|| {
                reject(
                    "bundle_module_missing",
                    "plugin is absent from verified archive",
                )
            })?;
        if manifest.runtime != RuntimeKindV2::Wasm || manifest.trust != TrustKindV2::Signed {
            return Err(reject(
                "bundle_wasm_contract_required",
                "external WASM requires signed WASM manifest",
            ));
        }
        let module = manifest
            .modules
            .iter()
            .find(|item| item.module_ref == module_ref)
            .ok_or_else(|| {
                reject(
                    "bundle_module_missing",
                    "module is absent from verified archive",
                )
            })?;
        if !module.targets.contains(&target) {
            return Err(reject(
                "bundle_artifact_target_mismatch",
                "module does not target requested plane",
            ));
        }
        let artifact = self
            .manifest
            .artifacts
            .iter()
            .find(|item| item.target == target && item.digest == module.artifact.digest)
            .ok_or_else(|| {
                reject(
                    "bundle_artifact_coverage_missing",
                    "module has no exact target artifact",
                )
            })?;
        let bytes = self
            .artifacts
            .get(&artifact.artifact_id)
            .ok_or_else(|| reject("bundle_artifact_missing", "verified artifact is absent"))?;
        Ok(VerifiedWasmArtifactV2 {
            reference: &self.reference,
            manifest,
            module,
            bytes,
        })
    }
}

/// Validate a signed external bundle against an independently supplied expected reference.
/// Approved permissions must come from the installing authority, never from the descriptor itself.
pub fn verify_signed_bundle_archive_v2(
    raw: &[u8],
    expected: &BundleReferenceV2,
    trusted_keys: &[TrustedEd25519KeyV2],
    approved_permissions: &BTreeSet<String>,
) -> Result<VerifiedBundleArchiveV2, BundleArchiveV2Error> {
    let files = read_files(raw)?;
    let descriptor = files
        .get("bundle.json")
        .ok_or_else(|| reject("bundle_descriptor_missing", "bundle.json is missing"))?;
    if descriptor.len() > MAX_DESCRIPTOR {
        return Err(reject(
            "bundle_descriptor_too_large",
            "descriptor exceeds limit",
        ));
    }
    let manifest = validation::parse_descriptor(descriptor)?;
    if manifest.bundle_id != expected.bundle_id
        || manifest.version != expected.version
        || manifest.digest != expected.digest
        || expected.source.is_empty()
        || expected.source.starts_with("builtin://")
    {
        return Err(reject(
            "bundle_reference_mismatch",
            "archive differs from external bundle reference",
        ));
    }
    let signature = manifest
        .signature
        .as_ref()
        .ok_or_else(|| reject("bundle_signature_required", "signed archive required"))?;
    let signature = STANDARD
        .decode(signature)
        .map_err(|_| reject("bundle_signature_invalid", "invalid signature base64"))?;
    if trusted_keys.is_empty() {
        return Err(reject(
            "bundle_signature_untrusted",
            "no trusted signing key",
        ));
    }
    if !trusted_keys.iter().any(|key| {
        UnparsedPublicKey::new(&ED25519, key.0)
            .verify(manifest.digest.as_bytes(), &signature)
            .is_ok()
    }) {
        return Err(reject(
            "bundle_signature_invalid",
            "signature verification failed",
        ));
    }
    if manifest
        .provenance
        .as_ref()
        .is_none_or(|value| value.trim().is_empty())
    {
        return Err(reject(
            "bundle_provenance_required",
            "signed provenance reference required",
        ));
    }
    let mut artifacts = BTreeMap::new();
    let mut declared_paths = BTreeSet::from(["bundle.json".to_owned()]);
    for artifact in &manifest.artifacts {
        if !declared_paths.insert(artifact.path.clone())
            || artifacts.contains_key(&artifact.artifact_id)
        {
            return Err(reject(
                "duplicate_bundle_artifact",
                "duplicate artifact identity or path",
            ));
        }
        let bytes = files
            .get(&artifact.path)
            .ok_or_else(|| reject("bundle_artifact_missing", "declared artifact is absent"))?;
        if bytes.len() as u64 != artifact.size_bytes {
            return Err(reject(
                "bundle_artifact_size_mismatch",
                "artifact size differs",
            ));
        }
        if format!("sha256:{:x}", Sha256::digest(bytes)) != artifact.digest {
            return Err(reject(
                "bundle_artifact_digest_mismatch",
                "artifact digest differs",
            ));
        }
        artifacts.insert(artifact.artifact_id.clone(), bytes.clone());
    }
    if files.keys().any(|path| !declared_paths.contains(path)) {
        return Err(reject(
            "undeclared_archive_entry",
            "archive contains undeclared file",
        ));
    }
    validation::validate_admission(&manifest, approved_permissions)?;
    Ok(VerifiedBundleArchiveV2 {
        manifest: Arc::new(manifest),
        artifacts: Arc::new(artifacts),
        reference: expected.clone(),
        approved_permissions: approved_permissions.clone(),
    })
}

fn read_files(raw: &[u8]) -> Result<BTreeMap<String, Vec<u8>>, BundleArchiveV2Error> {
    if raw.len() > MAX_ARCHIVE {
        return Err(reject("bundle_too_large", "archive exceeds limit"));
    }
    let mut archive = zip::ZipArchive::new(Cursor::new(raw))
        .map_err(|_| reject("bundle_archive_invalid", "invalid ZIP archive"))?;
    if archive.len() > MAX_FILES {
        return Err(reject(
            "bundle_file_limit_exceeded",
            "archive file limit exceeded",
        ));
    }
    let mut files = BTreeMap::new();
    let mut total = 0_u64;
    for index in 0..archive.len() {
        let mut entry = archive.by_index(index).map_err(|_| {
            reject(
                "bundle_entry_read_failed",
                "unreadable or encrypted ZIP entry",
            )
        })?;
        let name = entry.name().to_owned();
        if name.is_empty()
            || name.contains(['\\', '\0'])
            || name
                .split('/')
                .any(|part| part.is_empty() || part == "." || part == "..")
        {
            return Err(reject("unsafe_archive_path", "unsafe ZIP path"));
        }
        if entry
            .unix_mode()
            .is_some_and(|mode| mode & 0o170000 == 0o120000)
        {
            return Err(reject(
                "archive_symlink_forbidden",
                "ZIP symlink is forbidden",
            ));
        }
        if files.contains_key(&name) {
            return Err(reject("duplicate_archive_entry", "duplicate ZIP entry"));
        }
        total = total.checked_add(entry.size()).ok_or_else(|| {
            reject(
                "bundle_uncompressed_limit_exceeded",
                "uncompressed limit exceeded",
            )
        })?;
        if total > MAX_UNCOMPRESSED {
            return Err(reject(
                "bundle_uncompressed_limit_exceeded",
                "uncompressed limit exceeded",
            ));
        }
        let expected_size = entry.size();
        let mut bytes = Vec::new();
        entry
            .by_ref()
            .take(expected_size + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| reject("bundle_entry_read_failed", "invalid compressed ZIP entry"))?;
        if bytes.len() as u64 != expected_size {
            return Err(reject("bundle_entry_size_mismatch", "ZIP size mismatch"));
        }
        files.insert(name, bytes);
    }
    Ok(files)
}
