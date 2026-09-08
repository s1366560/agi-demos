//! Host-only local acceptance qualification. No HTTP or renderer input reaches
//! this type; the private initialization channel is its sole construction path.
use std::{
    fs,
    path::{Path, PathBuf},
};

use serde::Deserialize;

pub(crate) const PURPOSE: &str = "local-knowledge-acceptance-v1";
pub(crate) const PROFILE: &str = "memstack-local-knowledge-acceptance-v2";
pub(crate) const SNAPSHOT: &str =
    include_str!("../../../../../shared/profiles/memstack-local-knowledge-acceptance.v2.json");

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct LocalKnowledgeAcceptanceRequest {
    purpose: String,
    user_data_directory: PathBuf,
}

#[derive(Clone)]
pub(crate) struct LocalKnowledgeAcceptance {
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
        if !cfg!(debug_assertions) || self.purpose != PURPOSE || !legacy.is_empty() {
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
            user_data,
            data,
            workspace,
        })
    }
}

impl LocalKnowledgeAcceptance {
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

    pub(crate) fn require_profile(&self, profile_id: &str, digest: &str) -> Result<(), String> {
        let expected: serde_json::Value = serde_json::from_str(SNAPSHOT).map_err(invalid)?;
        if profile_id != PROFILE || expected["digest"].as_str() != Some(digest) {
            return Err("local knowledge acceptance requires the compiled profile digest".into());
        }
        self.require_storage(&self.data.path)
    }
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
