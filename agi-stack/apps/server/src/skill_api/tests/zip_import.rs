use super::*;

#[tokio::test]
async fn zip_import_package_matches_lifecycle_golden() {
    let bytes = zip_package(&[
        ("alpha-skill/SKILL.md", SAMPLE_IMPORT_SKILL_MD.as_bytes()),
        ("alpha-skill/references/README.md", b"details"),
        ("outside.txt", b"ignored"),
    ]);
    let (skill_md_content, resource_files) =
        crate::skill_api::zip_import::parse_skill_zip_package(bytes)
            .await
            .unwrap();
    assert_eq!(skill_md_content, SAMPLE_IMPORT_SKILL_MD);
    assert_eq!(
        resource_files,
        BTreeMap::from([("references/README.md".to_string(), "details".to_string())])
    );

    let service = DevSkillService::new("tenant-1");
    let imported = service
        .import_package(
            "u1",
            Some("tenant-1"),
            SkillImportPayload {
                skill_md_content,
                resource_files,
                scope: "tenant".to_string(),
                project_id: None,
                overwrite: false,
                change_summary: None,
            },
        )
        .await
        .unwrap();

    let actual = serde_json::to_value(imported).unwrap();
    let golden: Value = serde_json::from_str(include_str!(
        "../../../tests/golden/skill_zip_import_lifecycle.json"
    ))
    .unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[tokio::test]
async fn zip_import_encodes_binary_resources_like_python() {
    let bytes = zip_package(&[
        ("skill/SKILL.md", SAMPLE_IMPORT_SKILL_MD.as_bytes()),
        ("skill/assets/logo.bin", &[0, 159, 146, 150]),
        ("__MACOSX/ignored", b"ignored"),
        ("skill/.DS_Store", b"ignored"),
    ]);
    let (_, resource_files) = crate::skill_api::zip_import::parse_skill_zip_package(bytes)
        .await
        .unwrap();
    assert_eq!(resource_files.len(), 1);
    let encoded = resource_files.get("assets/logo.bin").unwrap();
    assert!(encoded.starts_with("base64:"));
}

#[tokio::test]
async fn zip_import_rejects_invalid_archives_and_unsafe_paths() {
    let invalid =
        crate::skill_api::zip_import::parse_skill_zip_package(b"not a zip".to_vec()).await;
    assert!(matches!(
        invalid,
        Err(SkillApiError {
            status: StatusCode::BAD_REQUEST,
            ..
        })
    ));

    let unsafe_path = crate::skill_api::zip_import::parse_skill_zip_package(zip_package(&[(
        "../SKILL.md",
        b"x",
    )]))
    .await;
    let err = unsafe_path.unwrap_err();
    assert_eq!(err.status, StatusCode::BAD_REQUEST);
    assert_eq!(err.detail, "Invalid skill zip package");
}
