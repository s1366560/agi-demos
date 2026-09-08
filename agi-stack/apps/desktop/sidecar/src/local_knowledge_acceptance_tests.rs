use super::*;
use std::os::unix::fs::{symlink, PermissionsExt};
use uuid::Uuid;

pub(crate) struct AcceptanceDirectories {
    pub(crate) profile: PathBuf,
    pub(crate) data: PathBuf,
    pub(crate) workspace: PathBuf,
}
impl AcceptanceDirectories {
    pub(crate) fn new() -> Self {
        let root = fs::canonicalize(std::env::temp_dir()).unwrap();
        let profile = root.join(format!("agistack-desktop-qa-profile-{}", Uuid::new_v4()));
        let workspace = root.join(format!("agistack-desktop-qa-workspace-{}", Uuid::new_v4()));
        let data = profile.join("runtime");
        for directory in [&profile, &data, &workspace] {
            fs::create_dir(directory).unwrap();
            fs::set_permissions(directory, fs::Permissions::from_mode(0o700)).unwrap();
        }
        Self {
            profile,
            data,
            workspace,
        }
    }
    pub(crate) fn qualification(&self) -> LocalKnowledgeAcceptance {
        self.request()
            .verify(&self.data, &self.workspace, &[])
            .unwrap()
    }
    fn request(&self) -> LocalKnowledgeAcceptanceRequest {
        LocalKnowledgeAcceptanceRequest {
            is_packaged: None,
            purpose: PURPOSE.into(),
            user_data_directory: self.profile.clone(),
        }
    }
}
impl Drop for AcceptanceDirectories {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.profile);
        let _ = fs::remove_dir_all(&self.workspace);
    }
}

#[test]
fn qualification_is_bound_to_private_isolated_directories_and_fixed_profile() {
    let directories = AcceptanceDirectories::new();
    let qualification = directories.qualification();
    qualification
        .require_current(&directories.data, &directories.workspace)
        .unwrap();
    let snapshot: serde_json::Value = serde_json::from_str(SNAPSHOT).unwrap();
    qualification
        .require_profile(PROFILE, snapshot["digest"].as_str().unwrap())
        .unwrap();
    assert!(qualification
        .require_profile("memstack-default-v2", snapshot["digest"].as_str().unwrap())
        .is_err());
    assert!(qualification
        .require_profile(PROFILE, &"a".repeat(64))
        .is_err());
    assert!(qualification
        .require_current(&directories.data, &directories.profile)
        .is_err());
}

#[test]
fn qualification_rejects_forged_purpose_legacy_migration_and_wrong_roots() {
    let directories = AcceptanceDirectories::new();
    let mut request = directories.request();
    request.purpose = "production".into();
    assert!(request
        .verify(&directories.data, &directories.workspace, &[])
        .is_err());
    request.purpose = PURPOSE.into();
    assert!(request
        .verify(
            &directories.data,
            &directories.workspace,
            std::slice::from_ref(&directories.profile)
        )
        .is_err());
    assert!(request
        .verify(&directories.workspace, &directories.workspace, &[])
        .is_err());
    assert!(request
        .verify(&directories.data, &directories.profile, &[])
        .is_err());
    assert!(request
        .verify(Path::new("relative"), &directories.workspace, &[])
        .is_err());
    let mut payload =
        serde_json::json!({"purpose":PURPOSE,"userDataDirectory":directories.profile});
    payload["actions"] = serde_json::json!(["sync_push"]);
    assert!(serde_json::from_value::<LocalKnowledgeAcceptanceRequest>(payload).is_err());
}

#[test]
fn qualification_rejects_symlinks_and_directory_replacement_after_admission() {
    let directories = AcceptanceDirectories::new();
    let qualification = directories.qualification();
    let alias = directories.workspace.join("profile-alias");
    symlink(&directories.profile, &alias).unwrap();
    assert!(directories
        .request()
        .verify(&alias.join("runtime"), &directories.workspace, &[])
        .is_err());
    fs::remove_file(&alias).unwrap();
    let moved = directories.profile.join("old-runtime");
    fs::rename(&directories.data, &moved).unwrap();
    symlink(&moved, &directories.data).unwrap();
    assert!(directories
        .request()
        .verify(&directories.data, &directories.workspace, &[])
        .is_err());
    assert!(qualification.require_storage(&directories.data).is_err());
    fs::remove_file(&directories.data).unwrap();
    fs::create_dir(&directories.data).unwrap();
    fs::set_permissions(&directories.data, fs::Permissions::from_mode(0o700)).unwrap();
    assert!(qualification.require_storage(&directories.data).is_err());
    assert!(directories
        .request()
        .verify(&directories.data, &directories.workspace, &[])
        .is_ok());
}

#[test]
fn qualification_rejects_late_permission_changes_and_non_temporary_directories() {
    let directories = AcceptanceDirectories::new();
    let qualification = directories.qualification();
    fs::set_permissions(&directories.workspace, fs::Permissions::from_mode(0o755)).unwrap();
    assert!(qualification.require_storage(&directories.data).is_err());
    assert!(directories
        .request()
        .verify(&directories.data, &directories.workspace, &[])
        .is_err());
    let nested = directories.profile.join("agistack-desktop-qa-nested");
    fs::create_dir(&nested).unwrap();
    fs::set_permissions(&nested, fs::Permissions::from_mode(0o700)).unwrap();
    assert!(directories
        .request()
        .verify(&directories.data, &nested, &[])
        .is_err());
}

impl AcceptanceDirectories {
    pub(crate) fn sync_qualification(&self) -> LocalKnowledgeAcceptance {
        let request: LocalKnowledgeAcceptanceRequest = serde_json::from_value(serde_json::json!({
            "purpose": SYNC_PURPOSE,
            "isPackaged": false,
            "userDataDirectory": self.profile,
        }))
        .unwrap();
        request.verify(&self.data, &self.workspace, &[]).unwrap()
    }
}

#[test]
fn sync_qualification_requires_explicit_purpose_and_unpacked_private_host() {
    let directories = AcceptanceDirectories::new();
    for payload in [
        serde_json::json!({"purpose":SYNC_PURPOSE,"userDataDirectory":directories.profile}),
        serde_json::json!({"purpose":SYNC_PURPOSE,"isPackaged":true,"userDataDirectory":directories.profile}),
        serde_json::json!({"purpose":"sync","isPackaged":false,"userDataDirectory":directories.profile}),
        serde_json::json!({"purpose":PURPOSE,"isPackaged":false,"userDataDirectory":directories.profile}),
    ] {
        let request: LocalKnowledgeAcceptanceRequest = serde_json::from_value(payload).unwrap();
        assert!(request
            .verify(&directories.data, &directories.workspace, &[])
            .is_err());
    }
    assert!(!directories.qualification().permits_sync());
    assert!(directories.sync_qualification().permits_sync());
}

#[test]
fn sync_qualification_requires_both_distinct_compiled_profiles() {
    let directories = AcceptanceDirectories::new();
    let qualification = directories.sync_qualification();
    let native: serde_json::Value = serde_json::from_str(SYNC_SNAPSHOT).unwrap();
    let cloud: serde_json::Value = serde_json::from_str(CLOUD_SYNC_SNAPSHOT).unwrap();
    let native_digest = native["digest"].as_str().unwrap();
    let cloud_digest = cloud["digest"].as_str().unwrap();
    qualification
        .require_profile(SYNC_PROFILE, native_digest)
        .unwrap();
    qualification
        .require_cloud_profile(CLOUD_SYNC_PROFILE, 1, cloud_digest)
        .unwrap();
    assert!(qualification
        .require_profile(PROFILE, native_digest)
        .is_err());
    assert!(qualification
        .require_cloud_profile(SYNC_PROFILE, 1, native_digest)
        .is_err());
    assert!(qualification
        .require_cloud_profile(CLOUD_SYNC_PROFILE, 1, native_digest)
        .is_err());
    assert!(qualification
        .require_cloud_profile(CLOUD_SYNC_PROFILE, 1, &"0".repeat(64))
        .is_err());
    assert!(directories
        .qualification()
        .require_cloud_profile(CLOUD_SYNC_PROFILE, 1, cloud_digest)
        .is_err());
    let moved = directories.profile.with_extension("previous");
    fs::rename(&directories.profile, &moved).unwrap();
    fs::create_dir(&directories.profile).unwrap();
    fs::set_permissions(&directories.profile, fs::Permissions::from_mode(0o700)).unwrap();
    assert!(qualification
        .require_cloud_profile(CLOUD_SYNC_PROFILE, 1, cloud_digest)
        .is_err());
    fs::remove_dir_all(moved).unwrap();
}

#[test]
fn cloud_generation_template_matches_python_protocol_vectors_and_rejects_stale_generation() {
    let vectors: serde_json::Value = serde_json::from_str(include_str!(
        "../../../../../shared/fixtures/cloud-knowledge-sync-acceptance-generations.v1.json"
    ))
    .unwrap();
    let directories = AcceptanceDirectories::new();
    let qualification = directories.sync_qualification();
    let entries = vectors["descriptors"].as_array().unwrap();
    assert_eq!(entries.len(), 3);
    for entry in entries {
        let generation = entry["generation"].as_u64().unwrap();
        let digest = entry["digest"].as_str().unwrap();
        assert_eq!(cloud_profile_digest(generation).unwrap(), digest);
        qualification
            .require_cloud_profile(CLOUD_SYNC_PROFILE, generation, digest)
            .unwrap();
        assert!(qualification
            .require_cloud_profile(CLOUD_SYNC_PROFILE, generation + 1, digest)
            .is_err());
    }
    assert!(cloud_profile_digest(0).is_err());
    assert!(cloud_profile_digest(u64::MAX).is_err());
}
