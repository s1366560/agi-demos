use std::collections::BTreeMap;
use std::io::{Cursor, Read};

use axum::extract::Multipart;
use base64::Engine;

use super::{SkillApiError, SkillImportPayload};

const INVALID_ZIP_PACKAGE: &str = "Invalid skill zip package";

#[derive(Debug, Default)]
struct ZipImportForm {
    archive: Option<ZipArchiveUpload>,
    scope: Option<String>,
    project_id: Option<String>,
    overwrite: bool,
    change_summary: Option<String>,
}

#[derive(Debug)]
struct ZipArchiveUpload {
    filename: Option<String>,
    bytes: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct SafeZipPath {
    parts: Vec<String>,
}

impl SafeZipPath {
    fn parse(name: &str) -> Result<Self, SkillApiError> {
        if name.starts_with('/') {
            return Err(SkillApiError::bad_request(INVALID_ZIP_PACKAGE));
        }
        let parts: Vec<String> = name
            .split('/')
            .filter(|part| !part.is_empty())
            .map(ToString::to_string)
            .collect();
        if parts.iter().any(|part| part == "..") {
            return Err(SkillApiError::bad_request(INVALID_ZIP_PACKAGE));
        }
        Ok(Self { parts })
    }

    fn file_name(&self) -> Option<&str> {
        self.parts.last().map(String::as_str)
    }

    fn is_ignored(&self) -> bool {
        self.parts.iter().any(|part| part == "__MACOSX") || self.file_name() == Some(".DS_Store")
    }

    fn parent(&self) -> Self {
        Self {
            parts: self
                .parts
                .iter()
                .take(self.parts.len().saturating_sub(1))
                .cloned()
                .collect(),
        }
    }

    fn strip_prefix(&self, root: &Self) -> Option<Self> {
        if root.parts.is_empty() {
            return Some(self.clone());
        }
        if !self.parts.starts_with(&root.parts) {
            return None;
        }
        Some(Self {
            parts: self.parts[root.parts.len()..].to_vec(),
        })
    }

    fn is_empty(&self) -> bool {
        self.parts.is_empty()
    }

    fn as_posix(&self) -> String {
        self.parts.join("/")
    }
}

pub(super) async fn skill_import_payload_from_multipart(
    mut multipart: Multipart,
) -> Result<SkillImportPayload, SkillApiError> {
    let mut form = ZipImportForm::default();
    while let Some(field) = multipart
        .next_field()
        .await
        .map_err(|_| SkillApiError::bad_request("Invalid skill zip package"))?
    {
        let name = field.name().map(ToString::to_string);
        let filename = field.file_name().map(ToString::to_string);
        let bytes = field
            .bytes()
            .await
            .map_err(|_| SkillApiError::bad_request("Invalid skill zip package"))?
            .to_vec();
        match name.as_deref() {
            Some("archive") => form.archive = Some(ZipArchiveUpload { filename, bytes }),
            Some("scope") => form.scope = Some(form_text(bytes)?),
            Some("project_id") => form.project_id = non_empty_form_text(bytes)?,
            Some("overwrite") => form.overwrite = parse_form_bool(&form_text(bytes)?),
            Some("change_summary") => form.change_summary = non_empty_form_text(bytes)?,
            _ => {}
        }
    }
    form.into_payload().await
}

impl ZipImportForm {
    async fn into_payload(self) -> Result<SkillImportPayload, SkillApiError> {
        let archive = self
            .archive
            .ok_or_else(|| SkillApiError::bad_request("Skill import file is required"))?;
        if archive
            .filename
            .as_deref()
            .is_some_and(|filename| !filename.to_ascii_lowercase().ends_with(".zip"))
        {
            return Err(SkillApiError::bad_request(
                "Skill import file must be a .zip archive",
            ));
        }

        let (skill_md_content, resource_files) = parse_skill_zip_package(archive.bytes).await?;
        Ok(SkillImportPayload {
            skill_md_content,
            resource_files,
            scope: self.scope.unwrap_or_else(super::default_scope),
            project_id: self.project_id,
            overwrite: self.overwrite,
            change_summary: self.change_summary,
        })
    }
}

pub(super) async fn parse_skill_zip_package(
    content: Vec<u8>,
) -> Result<(String, BTreeMap<String, String>), SkillApiError> {
    tokio::task::spawn_blocking(move || parse_skill_zip_package_blocking(content))
        .await
        .map_err(SkillApiError::internal)?
}

fn parse_skill_zip_package_blocking(
    content: Vec<u8>,
) -> Result<(String, BTreeMap<String, String>), SkillApiError> {
    let mut archive = zip::ZipArchive::new(Cursor::new(content))
        .map_err(|_| SkillApiError::bad_request(INVALID_ZIP_PACKAGE))?;
    let mut files = Vec::new();
    for index in 0..archive.len() {
        let file = archive
            .by_index(index)
            .map_err(|_| SkillApiError::bad_request(INVALID_ZIP_PACKAGE))?;
        if file.is_dir() {
            continue;
        }
        let path = SafeZipPath::parse(file.name())?;
        if path.is_ignored() || path.is_empty() {
            continue;
        }
        files.push((index, path));
    }

    let skill_md_files: Vec<(usize, SafeZipPath)> = files
        .iter()
        .filter(|(_, path)| path.file_name() == Some("SKILL.md"))
        .cloned()
        .collect();
    let [(skill_md_index, skill_md_path)] = skill_md_files.as_slice() else {
        return if skill_md_files.is_empty() {
            Err(SkillApiError::bad_request(
                "Skill zip package must contain SKILL.md",
            ))
        } else {
            Err(SkillApiError::bad_request(
                "Skill zip package must contain exactly one SKILL.md",
            ))
        };
    };

    let skill_md_content = read_zip_file(&mut archive, *skill_md_index)?;
    let skill_md_content = String::from_utf8(skill_md_content)
        .map_err(|_| SkillApiError::bad_request("SKILL.md must be UTF-8 text"))?;
    let skill_root = skill_md_path.parent();
    let mut resource_files = BTreeMap::new();
    for (index, path) in files {
        if path == *skill_md_path {
            continue;
        }
        let Some(relative_path) = path.strip_prefix(&skill_root) else {
            continue;
        };
        if relative_path.is_empty() || relative_path.file_name() == Some("") {
            continue;
        }
        let content = read_zip_file(&mut archive, index)?;
        resource_files.insert(relative_path.as_posix(), resource_text(content));
    }
    Ok((skill_md_content, resource_files))
}

fn read_zip_file(
    archive: &mut zip::ZipArchive<Cursor<Vec<u8>>>,
    index: usize,
) -> Result<Vec<u8>, SkillApiError> {
    let mut file = archive
        .by_index(index)
        .map_err(|_| SkillApiError::bad_request(INVALID_ZIP_PACKAGE))?;
    let mut content = Vec::new();
    file.read_to_end(&mut content)
        .map_err(|_| SkillApiError::bad_request(INVALID_ZIP_PACKAGE))?;
    Ok(content)
}

fn resource_text(content: Vec<u8>) -> String {
    match String::from_utf8(content) {
        Ok(text) => text,
        Err(err) => {
            let encoded = base64::engine::general_purpose::STANDARD.encode(err.into_bytes());
            format!("base64:{encoded}")
        }
    }
}

fn form_text(bytes: Vec<u8>) -> Result<String, SkillApiError> {
    String::from_utf8(bytes).map_err(|_| SkillApiError::bad_request(INVALID_ZIP_PACKAGE))
}

fn non_empty_form_text(bytes: Vec<u8>) -> Result<Option<String>, SkillApiError> {
    let value = form_text(bytes)?.trim().to_string();
    Ok(if value.is_empty() { None } else { Some(value) })
}

fn parse_form_bool(value: &str) -> bool {
    matches!(
        value.trim().to_ascii_lowercase().as_str(),
        "1" | "true" | "yes" | "on"
    )
}
