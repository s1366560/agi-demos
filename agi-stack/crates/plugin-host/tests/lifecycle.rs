//! Manifest parsing, plugin-shape classification, and the enable/disable
//! lifecycle (the native path — no WASM needed).

use agistack_plugin_host::host::PluginHost;
use agistack_plugin_host::manifest::PluginManifest;
use agistack_plugin_host::native::NativeToolFactory;
use agistack_plugin_host::registry::HotPlugRegistry;
use agistack_plugin_host::tool::PluginShape;
use futures::executor::block_on;

#[test]
fn classifies_plugin_shapes_from_actual_contributions() {
    let plain =
        PluginManifest::from_json(r#"{ "name": "p", "tools": [ { "name": "a" } ] }"#).unwrap();
    assert_eq!(plain.shape(), PluginShape::PlainCapability);

    let hybrid = PluginManifest::from_json(
        r#"{ "name": "h", "tools": [ { "name": "a" } ], "providers": ["openai"] }"#,
    )
    .unwrap();
    assert_eq!(hybrid.shape(), PluginShape::HybridCapability);

    let hook_only =
        PluginManifest::from_json(r#"{ "name": "k", "hooks": ["before_prompt_build"] }"#).unwrap();
    assert_eq!(hook_only.shape(), PluginShape::HookOnly);

    let non_cap = PluginManifest::from_json(r#"{ "name": "n", "skills": ["docs"] }"#).unwrap();
    // skills are a non-tool capability kind -> still a (single-kind) capability.
    assert_eq!(non_cap.shape(), PluginShape::PlainCapability);

    let empty = PluginManifest::from_json(r#"{ "name": "e" }"#).unwrap();
    assert_eq!(empty.shape(), PluginShape::NonCapability);
}

#[test]
fn enable_registers_and_disable_unregisters_exactly_its_tools() {
    let registry = HotPlugRegistry::new();
    let host = PluginHost::new(registry.clone());
    let factory = NativeToolFactory;

    let manifest = PluginManifest::from_json(
        r#"{
            "name": "notes-pack",
            "version": "0.1.0",
            "tools": [
                { "name": "note_create", "version": "0.1.0" },
                { "name": "note_search", "version": "0.1.0" }
            ]
        }"#,
    )
    .unwrap();

    // Nothing registered yet.
    assert!(registry.names().is_empty());
    assert!(!host.is_enabled("notes-pack").unwrap());

    // Enable: both declared tools appear atomically.
    let added = host.enable(&manifest, &factory).unwrap();
    assert_eq!(
        added,
        vec!["note_create".to_string(), "note_search".to_string()]
    );
    assert!(host.is_enabled("notes-pack").unwrap());
    assert_eq!(
        registry.names(),
        vec!["note_create".to_string(), "note_search".to_string()]
    );

    // The freshly hot-loaded tool actually works.
    let out = block_on(registry.invoke("note_create", r#"{"title":"x"}"#)).unwrap();
    assert!(out.contains("note_create"), "unexpected: {out}");

    // Re-enabling the same plugin is rejected (already enabled).
    assert!(host.enable(&manifest, &factory).is_err());

    // Disable: exactly its tools are removed, registry returns to empty.
    let removed = host.disable("notes-pack").unwrap();
    assert_eq!(
        removed,
        vec!["note_create".to_string(), "note_search".to_string()]
    );
    assert!(!host.is_enabled("notes-pack").unwrap());
    assert!(registry.names().is_empty());
}

#[test]
fn disabling_one_plugin_leaves_others_intact() {
    let registry = HotPlugRegistry::new();
    let host = PluginHost::new(registry.clone());
    let factory = NativeToolFactory;

    let a =
        PluginManifest::from_json(r#"{ "name": "a", "tools": [ { "name": "a_tool" } ] }"#).unwrap();
    let b =
        PluginManifest::from_json(r#"{ "name": "b", "tools": [ { "name": "b_tool" } ] }"#).unwrap();

    host.enable(&a, &factory).unwrap();
    host.enable(&b, &factory).unwrap();
    assert_eq!(
        registry.names(),
        vec!["a_tool".to_string(), "b_tool".to_string()]
    );

    host.disable("a").unwrap();
    assert_eq!(registry.names(), vec!["b_tool".to_string()]);
    assert_eq!(host.enabled_plugins().unwrap(), vec!["b".to_string()]);
}
