//! Host-only local acceptance qualification. No HTTP or renderer input reaches
//! this type; the private initialization channel is its sole construction path.
use std::{
    fs,
    path::{Path, PathBuf},
};

use serde::Deserialize;

pub(crate) const PURPOSE: &str = "local-knowledge-acceptance-v1";
pub(crate) const SYNC_PURPOSE: &str = "knowledge-sync-acceptance-v1";
pub(crate) const SYNC_PROFILE: &str = "memstack-knowledge-sync-acceptance-v2";
pub(crate) const SYNC_SNAPSHOT: &str =
    include_str!("../../../../../shared/profiles/memstack-knowledge-sync-acceptance.v2.json");

pub(crate) const CLOUD_SYNC_PROFILE: &str = "memstack-cloud-knowledge-sync-acceptance-v2";
pub(crate) const CLOUD_SYNC_SNAPSHOT: &str =
    include_str!("../../../../../shared/profiles/memstack-cloud-knowledge-sync-acceptance.v2.json");

pub(crate) const PROFILE: &str = "memstack-local-knowledge-acceptance-v2";
pub(crate) const SNAPSHOT: &str =
    include_str!("../../../../../shared/profiles/memstack-local-knowledge-acceptance.v2.json");

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct LocalKnowledgeAcceptanceRequest {
    purpose: String,
    #[serde(default)]
    is_packaged: Option<bool>,
    user_data_directory: PathBuf,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum AcceptancePurpose {
    LocalKnowledge,
    KnowledgeSync,
}

#[derive(Clone)]
pub(crate) struct LocalKnowledgeAcceptance {
    purpose: AcceptancePurpose,
    user_data: Directory,
    data: Directory,
    workspace: Directory,
}

#[derive(Clone)]
struct Directory {
    path: PathBuf,
    #[cfg(unix)]
    identity: (u64, u64, u32),
}

impl LocalKnowledgeAcceptanceRequest {
    pub(crate) fn verify(
        &self,
        data: &Path,
        workspace: &Path,
        legacy: &[PathBuf],
    ) -> Result<LocalKnowledgeAcceptance, String> {
        let purpose = match (self.purpose.as_str(), self.is_packaged) {
            (PURPOSE, None) => AcceptancePurpose::LocalKnowledge,
            (SYNC_PURPOSE, Some(false)) => AcceptancePurpose::KnowledgeSync,
            _ => {
                return Err(
                    "knowledge acceptance requires an explicit supported host purpose".into(),
                )
            }
        };
        if !cfg!(debug_assertions) || !legacy.is_empty() {
            return Err("local knowledge acceptance requires an isolated development host".into());
        }
        let temporary_input = std::env::temp_dir();
        let temporary = fs::canonicalize(&temporary_input).map_err(invalid)?;
        for path in [&self.user_data_directory, workspace] {
            if path.parent() != Some(temporary_input.as_path())
                && path.parent() != Some(temporary.as_path())
            {
                return Err("local knowledge acceptance requires direct temporary paths".into());
            }
        }
        let user_data = Directory::read(&self.user_data_directory)?;
        if data != self.user_data_directory.join("runtime")
            && data != user_data.path.join("runtime")
        {
            return Err(
                "local knowledge acceptance data path must be the bound runtime child".into(),
            );
        }
        let data = Directory::read(data)?;
        let workspace = Directory::read(workspace)?;
        for directory in [&user_data, &workspace] {
            if directory.path.parent() != Some(temporary.as_path())
                || !directory
                    .path
                    .file_name()
                    .and_then(|name| name.to_str())
                    .is_some_and(|name| name.starts_with("agistack-desktop-qa-"))
            {
                return Err(
                    "local knowledge acceptance requires direct temporary QA directories".into(),
                );
            }
        }
        if user_data.path == workspace.path || data.path != user_data.path.join("runtime") {
            return Err(
                "local knowledge acceptance requires distinct bound data and workspace roots"
                    .into(),
            );
        }
        #[cfg(unix)]
        if user_data.identity.2 != data.identity.2 || user_data.identity.2 != workspace.identity.2 {
            return Err("local knowledge acceptance directory owners differ".into());
        }
        Ok(LocalKnowledgeAcceptance {
            purpose,
            user_data,
            data,
            workspace,
        })
    }
}

impl LocalKnowledgeAcceptance {
    pub(crate) fn permits_sync(&self) -> bool {
        self.purpose == AcceptancePurpose::KnowledgeSync
    }

    pub(crate) fn snapshot(&self) -> &'static str {
        if self.permits_sync() {
            SYNC_SNAPSHOT
        } else {
            SNAPSHOT
        }
    }

    pub(crate) fn require_current(&self, data: &Path, workspace: &Path) -> Result<(), String> {
        for directory in [&self.user_data, &self.data, &self.workspace] {
            let current = Directory::read(&directory.path)?;
            #[cfg(unix)]
            if current.identity != directory.identity {
                return Err("local knowledge acceptance directory identity changed".into());
            }
        }
        if fs::canonicalize(data).map_err(invalid)? != self.data.path
            || fs::canonicalize(workspace).map_err(invalid)? != self.workspace.path
        {
            return Err("local knowledge acceptance runtime scope changed".into());
        }
        Ok(())
    }

    pub(crate) fn require_storage(&self, data: &Path) -> Result<(), String> {
        self.require_current(data, &self.workspace.path)
    }

    pub(crate) fn require_cloud_profile(
        &self,
        profile_id: &str,
        generation: u64,
        digest: &str,
    ) -> Result<(), String> {
        if !self.permits_sync()
            || profile_id != CLOUD_SYNC_PROFILE
            || cloud_profile_digest(generation)? != digest
        {
            return Err(
                "knowledge sync acceptance requires the compiled cloud QA profile digest".into(),
            );
        }
        self.require_storage(&self.data.path)
    }

    pub(crate) fn require_profile(&self, profile_id: &str, digest: &str) -> Result<(), String> {
        let expected: serde_json::Value = serde_json::from_str(self.snapshot()).map_err(invalid)?;
        let profile = if self.permits_sync() {
            SYNC_PROFILE
        } else {
            PROFILE
        };
        if profile_id != profile || expected["digest"].as_str() != Some(digest) {
            return Err("local knowledge acceptance requires the compiled profile digest".into());
        }
        self.require_storage(&self.data.path)
    }
}

/// Preserve the compiled cloud profile's complete content while rebinding only its generation.
/// Snapshot digests include generation, so generation 1 is not a runtime comparison constant.
pub(crate) fn cloud_profile_digest(generation: u64) -> Result<String, String> {
    use agistack_plugin_host::protocol_v2::parse_profile_snapshot_v2;
    use sha2::{Digest, Sha256};
    if generation == 0 || generation > 9_007_199_254_740_991 {
        return Err("knowledge sync cloud generation is outside the protocol integer range".into());
    }
    let compiled = parse_profile_snapshot_v2(CLOUD_SYNC_SNAPSHOT).map_err(invalid)?;
    if compiled.profile_id != CLOUD_SYNC_PROFILE || compiled.generation != 1 {
        return Err("knowledge sync cloud QA template is invalid".into());
    }
    let mut value: serde_json::Value =
        serde_json::from_str(CLOUD_SYNC_SNAPSHOT).map_err(invalid)?;
    value["generation"] = serde_json::json!(generation);
    value
        .as_object_mut()
        .ok_or("knowledge sync cloud QA template is not an object")?
        .remove("digest");
    Ok(format!(
        "{:x}",
        Sha256::digest(serde_jcs::to_vec(&value).map_err(invalid)?)
    ))
}

impl Directory {
    fn read(path: &Path) -> Result<Self, String> {
        if !path.is_absolute()
            || path
                .components()
                .any(|part| matches!(part, std::path::Component::ParentDir))
        {
            return Err("local knowledge acceptance directory must be absolute".into());
        }
        let metadata = fs::symlink_metadata(path).map_err(invalid)?;
        if !metadata.is_dir() || metadata.file_type().is_symlink() {
            return Err("local knowledge acceptance requires real directories".into());
        }
        let canonical = fs::canonicalize(path).map_err(invalid)?;
        // TEMP itself may use the platform's canonical alias (/var -> /private/var).
        // No symbolic link below that root is permitted.
        if fs::canonicalize(path.parent().ok_or("missing directory parent")?)
            .map_err(invalid)?
            .join(path.file_name().ok_or("missing directory name")?)
            != canonical
        {
            return Err("local knowledge acceptance directory traverses a symbolic link".into());
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            if metadata.mode() & 0o777 != 0o700 {
                return Err("local knowledge acceptance directory must be private".into());
            }
            Ok(Self {
                path: canonical,
                identity: (metadata.dev(), metadata.ino(), metadata.uid()),
            })
        }
        #[cfg(not(unix))]
        {
            let _ = canonical;
            Err(
                "local knowledge acceptance directory verification is unsupported on this platform"
                    .into(),
            )
        }
    }
}

fn invalid(error: impl std::fmt::Display) -> String {
    format!("local knowledge acceptance qualification failed: {error}")
}

#[cfg(all(test, unix))]
#[path = "local_knowledge_acceptance_tests.rs"]
pub(crate) mod tests;
