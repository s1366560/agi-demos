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

#[test]
fn computer_use_tools_carry_roster_authority_metadata() {
    let observation = tool_metadata("computer_get_app_state").expect("observation roster entry");
    assert_eq!(observation.effect, ToolEffect::Read);
    let listing = tool_metadata("computer_list_apps").expect("listing roster entry");
    assert_eq!(listing.effect, ToolEffect::Read);
    for tool in [
        "computer_click",
        "computer_type_text",
        "computer_press_key",
        "computer_scroll",
        "computer_set_value",
        "computer_drag",
        "computer_secondary_action",
        "computer_paste",
    ] {
        let metadata = tool_metadata(tool).unwrap_or_else(|| panic!("{tool} roster entry"));
        assert_eq!(metadata.effect, ToolEffect::Mutate, "{tool} must consume a grant");
    }
}

#[test]
fn computer_use_timeline_payloads_are_not_wiped_by_redaction() {
    let input = r#"{"app":"Finder","disable_diff":true}"#;
    let output = r#"{"app":"Finder","text":"[0] window","screenshot":{"url":"file:///tmp/x.jpg"}}"#;
    for tool in ["computer_list_apps", "computer_get_app_state", "computer_click"] {
        let redacted_input = redact_tool_payload(tool, input);
        assert!(
            redacted_input.starts_with('{'),
            "{tool} input must survive redaction, got: {redacted_input}"
        );
        let redacted_output = redact_tool_payload(tool, output);
        assert!(
            redacted_output.starts_with('{'),
            "{tool} output must survive redaction, got: {redacted_output}"
        );
    }
}
