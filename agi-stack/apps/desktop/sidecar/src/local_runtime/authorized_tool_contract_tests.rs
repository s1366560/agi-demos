#[test]
fn authorized_contract_roster_hides_forbidden_dynamic_metadata() -> Result<(), String> {
    struct DescribedDynamic;
    #[async_trait]
    impl ToolHost for DescribedDynamic {
        fn list_tools(&self) -> Vec<String> {
            vec!["read".into(), "mcp__private__mutate".into()]
        }
        fn tool_definition(&self, name: &str) -> Option<agistack_core::ports::ToolDefinition> {
            Some(agistack_core::ports::ToolDefinition::new(
                name,
                format!("definition:{name}"),
                json!({"type":"object","required":["argument"]}),
            ))
        }
        async fn call(&self, _: &str, _: &str) -> CoreResult<String> {
            unreachable!()
        }
    }
    let (root, store, run, _) = running_host(DesktopPermissionProfile::ReadOnly)?;
    let metadata = BTreeMap::from([(
        "mcp__private__mutate".into(),
        ToolMetadata {
            name: "mcp__private__mutate".into(),
            effect: ToolEffect::Mutate,
            sensitive_input_fields: BTreeSet::new(),
        },
    )]);
    let host = AuthorizedRunToolHost::with_dynamic_metadata(
        Arc::new(DescribedDynamic),
        store,
        run,
        metadata,
    );
    let definitions = host.tool_definitions().map_err(|error| error.to_string())?;
    assert_eq!(definitions.len(), 1);
    assert_eq!(definitions[0].name, "read");
    assert_eq!(
        definitions[0].input_schema.as_ref().unwrap()["required"],
        json!(["argument"])
    );
    assert!(host.tool_definition("mcp__private__mutate").is_none());
    std::fs::remove_dir_all(root).map_err(|error| error.to_string())?;
    Ok(())
}
