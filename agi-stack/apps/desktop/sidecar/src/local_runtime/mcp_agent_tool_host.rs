//! Project-scoped MCP tools exposed to the local ReAct engine.
//!
//! Tool identity and authorization are structural. The model decides whether a
//! tool is semantically appropriate; this host only exposes enabled, healthy,
//! already-discovered tools in the active tenant/project scope and dispatches
//! exact structured calls through [`McpSupervisor`].

use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
};

use agistack_core::ports::{CoreError, CoreResult, ToolDefinition, ToolHost};
use async_trait::async_trait;
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use super::{
    authorized_tool_host,
    mcp_supervisor::{McpAppDefinition, McpCatalogLease, McpScope, McpSupervisor},
    tool_authority::{canonical_json_digest, ToolEffect, ToolMetadata},
};

const TOOL_PREFIX: &str = "mcp__";
const MAX_MCP_IDENTIFIER_BYTES: usize = 200;
const MAX_SERVER_SLUG_BYTES: usize = 19;
const MAX_TOOL_SLUG_BYTES: usize = 19;
const TOOL_IDENTITY_DIGEST_HEX_BYTES: usize = 16;
// Keep names portable to OpenAI-compatible function/tool schemas.
const MAX_EXPOSED_TOOL_NAME_BYTES: usize = 64;

#[derive(Clone)]
struct McpAgentTool {
    server_id: String,
    server_name: String,
    tool_name: String,
    definition: ToolDefinition,
    metadata: ToolMetadata,
}

/// Snapshot of the active project-scoped MCP tool catalog for one agent run.
pub(super) struct McpAgentToolHost {
    supervisor: Arc<McpSupervisor>,
    scope: McpScope,
    run_id: String,
    catalog_lease: McpCatalogLease,
    apps: Vec<McpAppDefinition>,
    app_events: Option<(Arc<super::LocalRuntimeState>, String, String)>,
    tools: BTreeMap<String, McpAgentTool>,
    legacy_aliases: BTreeMap<String, String>,
    advertised_aliases: BTreeSet<String>,
}

impl McpAgentToolHost {
    pub(super) fn new(
        supervisor: Arc<McpSupervisor>,
        scope: McpScope,
        run_id: String,
        allowed_servers: Option<&[String]>,
    ) -> Result<Self, String> {
        let mut tools: BTreeMap<String, McpAgentTool> = BTreeMap::new();
        let mut dispatch_aliases: BTreeMap<String, Option<String>> = BTreeMap::new();
        let mut advertised_alias_candidates = BTreeSet::new();
        let (servers, catalog_lease) = supervisor
            .acquire_catalog(&scope)
            .map_err(|error| error.to_string())?;
        let apps = supervisor
            .apps_pinned(&catalog_lease, &scope)
            .map_err(|error| error.to_string())?;
        for server in servers.into_iter().filter(|server| {
            server.enabled
                && server.runtime_status == "healthy"
                && valid_mcp_identifier(&server.id)
                && valid_mcp_identifier(&server.name)
                && server_allowed(allowed_servers, &server.id, &server.name)
        }) {
            for definition in &server.discovered_tools {
                let Some(tool_name) = definition.get("name").and_then(Value::as_str) else {
                    continue;
                };
                if !valid_mcp_identifier(tool_name) {
                    continue;
                }
                let exposed_name = exposed_tool_name(&server.id, &server.name, tool_name);
                if !canonical_name_available(&tools, &exposed_name, &server.id, tool_name)? {
                    continue;
                }
                let legacy_name = legacy_exposed_tool_name(&server.id, tool_name);
                insert_dispatch_alias(&mut dispatch_aliases, legacy_name, &exposed_name);
                if let Some(model_alias) = model_alias_name(&server.name) {
                    insert_dispatch_alias(
                        &mut dispatch_aliases,
                        model_alias.clone(),
                        &exposed_name,
                    );
                    advertised_alias_candidates.insert(model_alias);
                }
                tools.insert(
                    exposed_name.clone(),
                    McpAgentTool {
                        server_id: server.id.clone(),
                        server_name: server.name.clone(),
                        tool_name: tool_name.to_string(),
                        definition: ToolDefinition {
                            name: exposed_name.clone(),
                            description: definition
                                .get("description")
                                .and_then(Value::as_str)
                                .map(str::to_string),
                            input_schema: definition.get("inputSchema").cloned(),
                        },
                        metadata: ToolMetadata {
                            name: exposed_name,
                            effect: ToolEffect::Mutate,
                            sensitive_input_fields: authorized_tool_host::sensitive_input_fields(),
                        },
                    },
                );
            }
        }
        let legacy_aliases: BTreeMap<String, String> = dispatch_aliases
            .into_iter()
            .filter_map(|(alias, target)| {
                target
                    .filter(|canonical| !tools.contains_key(&alias) || canonical == &alias)
                    .map(|canonical| (alias, canonical))
            })
            .collect();
        let advertised_aliases = advertised_alias_candidates
            .into_iter()
            .filter(|alias| legacy_aliases.contains_key(alias))
            .collect();
        Ok(Self {
            supervisor,
            scope,
            run_id,
            catalog_lease,
            apps,
            app_events: None,
            tools,
            legacy_aliases,
            advertised_aliases,
        })
    }

    pub(super) fn authority_metadata_by_name(&self) -> BTreeMap<String, ToolMetadata> {
        let mut metadata: BTreeMap<_, _> = self
            .tools
            .iter()
            .map(|(name, item)| (name.clone(), item.metadata.clone()))
            .collect();
        for (alias, canonical) in &self.legacy_aliases {
            let Some(item) = self.tools.get(canonical) else {
                continue;
            };
            let mut alias_metadata = item.metadata.clone();
            alias_metadata.name.clone_from(alias);
            metadata.insert(alias.clone(), alias_metadata);
        }
        metadata
    }

    pub(super) fn with_app_events(
        mut self,
        state: Arc<super::LocalRuntimeState>,
        conversation_id: String,
        message_id: String,
    ) -> Self {
        self.app_events = Some((state, conversation_id, message_id));
        self
    }

    fn tool_by_exposed_name(&self, name: &str) -> Option<&McpAgentTool> {
        resolve_exposed_tool(&self.tools, &self.legacy_aliases, name)
    }

    /// Resolve app metadata from the scoped catalog, never from tool-returned claims.
    pub(super) async fn app_result(
        &self,
        name: &str,
        input: Value,
        output: Value,
    ) -> Result<Option<Value>, String> {
        let Some(tool) = self.tool_by_exposed_name(name) else {
            return Ok(None);
        };
        let app = self
            .apps
            .iter()
            .find(|app| app.server_id == tool.server_id && app.tool_name == tool.tool_name);
        let Some(app) = app else {
            return Ok(None);
        };
        let Some(uri) = app.resource_uri.as_deref() else {
            return Ok(None);
        };
        let contents = self
            .supervisor
            .read_resource_pinned(&self.catalog_lease, &self.scope, &tool.server_id, uri)
            .await
            .map_err(|error| error.reason_code().to_string())?;
        let html = contents
            .iter()
            .find_map(|content| {
                let matches_uri = content.get("uri").and_then(Value::as_str) == Some(uri);
                let is_html = content
                    .get("mimeType")
                    .and_then(Value::as_str)
                    .is_some_and(|mime| {
                        mime.split(';')
                            .next()
                            .is_some_and(|kind| kind == "text/html")
                    });
                (matches_uri && is_html)
                    .then(|| content.get("text").and_then(Value::as_str))
                    .flatten()
            })
            .ok_or_else(|| "local_mcp_app_html_unavailable".to_string())?;
        Ok(Some(json!({
            "app_id": app.id,
            "project_id": self.scope.project_id,
            "server_name": tool.server_name,
            "tool_name": tool.tool_name,
            "resource_uri": uri,
            "resource_html": html,
            "ui_metadata": app.ui_metadata,
            "tool_input": input,
            "tool_result": output,
        })))
    }
}

#[async_trait]
impl ToolHost for McpAgentToolHost {
    fn tool_definition(&self, name: &str) -> Option<ToolDefinition> {
        let mut definition = self.tool_by_exposed_name(name)?.definition.clone();
        // Aliases share the discovered contract but retain their advertised identity.
        definition.name = name.to_string();
        Some(definition)
    }

    fn list_tools(&self) -> Vec<String> {
        self.tools
            .keys()
            .cloned()
            .chain(self.advertised_aliases.iter().cloned())
            .collect()
    }

    fn can_dispatch(&self, tool: &str) -> bool {
        self.tool_by_exposed_name(tool).is_some()
    }

    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        let definition = self
            .tool_by_exposed_name(tool)
            .ok_or_else(|| CoreError::Tool(format!("unknown MCP agent tool: {tool}")))?;
        let arguments: Value = serde_json::from_str(input_json)
            .map_err(|error| CoreError::Tool(format!("invalid MCP tool input: {error}")))?;
        if !arguments.is_object() {
            return Err(CoreError::Tool(
                "MCP tool input must be a JSON object".to_string(),
            ));
        }
        let call_digest = canonical_json_digest(&json!({
            "run_id": self.run_id,
            "tool": definition.metadata.name.as_str(),
            "arguments": arguments,
        }))
        .map_err(|error| CoreError::Tool(error.to_string()))?;
        let outcome = self
            .supervisor
            .call_tool_pinned(
                &self.catalog_lease,
                &self.scope,
                &definition.server_id,
                &definition.tool_name,
                arguments.clone(),
                &format!("agent-{call_digest}"),
            )
            .await
            .map_err(|error| {
                CoreError::Tool(format!("{}: {}", error.reason_code(), error.detail()))
            })?;
        let result = json!({
            "server_name": definition.server_name,
            "tool_name": definition.tool_name,
            "content": outcome.content,
            "is_error": outcome.is_error,
            "duplicate": outcome.duplicate,
        });
        if !outcome.is_error {
            let fields = &definition.metadata.sensitive_input_fields;
            publish_app_result(
                self,
                tool,
                &call_digest,
                super::tool_authority::redact_sensitive_fields(&arguments, fields),
                super::tool_authority::redact_sensitive_fields(&result, fields),
            )
            .await;
        }
        serde_json::to_string(&result).map_err(|error| CoreError::Tool(error.to_string()))
    }
}

fn server_allowed(allowed: Option<&[String]>, server_id: &str, server_name: &str) -> bool {
    allowed.map_or(true, |values| {
        values
            .iter()
            .any(|value| value == "*" || value == server_id || value == server_name)
    })
}

async fn publish_app_result(
    host: &McpAgentToolHost,
    tool: &str,
    call_id: &str,
    input: Value,
    output: Value,
) {
    let Some((state, conversation_id, message_id)) = host.app_events.as_ref() else {
        return;
    };
    match host.app_result(tool, input, output).await {
        Ok(Some(mut payload)) => {
            payload["message_id"] = json!(message_id);
            payload["tool_call_id"] = json!(call_id);
            let item = state.timeline_item(
                "mcp_app_result",
                conversation_id.clone(),
                None,
                None,
                None,
                payload,
            );
            state.append_timeline(conversation_id, item);
        }
        Ok(None) => {}
        Err(reason) => {
            tracing::warn!(reason_code = %reason, "MCP app resource unavailable");
            let item = state.timeline_item(
                "mcp_app_result",
                conversation_id.clone(),
                None,
                None,
                None,
                json!({
                    "tool_name": tool,
                    "message_id": message_id,
                    "tool_call_id": call_id,
                    "error": reason,
                }),
            );
            state.append_timeline(conversation_id, item);
        }
    }
}

fn valid_mcp_identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= MAX_MCP_IDENTIFIER_BYTES
        && !value.chars().any(char::is_control)
}

fn exposed_tool_name(server_id: &str, server_name: &str, tool_name: &str) -> String {
    let server_slug = readable_slug(server_name, MAX_SERVER_SLUG_BYTES, "server");
    let tool_slug = readable_slug(tool_name, MAX_TOOL_SLUG_BYTES, "tool");
    let digest = stable_tool_identity_digest(server_id, tool_name);
    let exposed = format!("{TOOL_PREFIX}{server_slug}__{tool_slug}__{digest}");
    debug_assert!(exposed.len() <= MAX_EXPOSED_TOOL_NAME_BYTES);
    exposed
}

pub(super) fn legacy_exposed_tool_name(server_id: &str, tool_name: &str) -> String {
    format!(
        "{TOOL_PREFIX}{}__{}",
        URL_SAFE_NO_PAD.encode(server_id.as_bytes()),
        URL_SAFE_NO_PAD.encode(tool_name.as_bytes())
    )
}

fn model_alias_name(server_name: &str) -> Option<String> {
    let value = server_name.trim();
    if value.is_empty()
        || value.len() > MAX_EXPOSED_TOOL_NAME_BYTES
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
    {
        return None;
    }
    Some(value.to_string())
}

fn insert_dispatch_alias(
    aliases: &mut BTreeMap<String, Option<String>>,
    alias: String,
    canonical: &str,
) {
    aliases
        .entry(alias)
        .and_modify(|target| {
            if target.as_deref() != Some(canonical) {
                *target = None;
            }
        })
        .or_insert_with(|| Some(canonical.to_string()));
}

fn readable_slug(value: &str, max_bytes: usize, fallback: &str) -> String {
    let mut slug = String::with_capacity(max_bytes.min(value.len()));
    let mut pending_separator = false;
    for character in value.chars() {
        if character.is_ascii_alphanumeric() {
            if pending_separator && !slug.is_empty() && slug.len() < max_bytes {
                slug.push('_');
            }
            pending_separator = false;
            if slug.len() == max_bytes {
                break;
            }
            slug.push(character.to_ascii_lowercase());
        } else if !slug.is_empty() {
            pending_separator = true;
        }
    }
    if slug.is_empty() {
        fallback.to_string()
    } else {
        slug
    }
}

fn stable_tool_identity_digest(server_id: &str, tool_name: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"memstack-mcp-agent-tool-name:v2\0");
    for value in [server_id, tool_name] {
        hasher.update((value.len() as u64).to_be_bytes());
        hasher.update(value.as_bytes());
    }
    let digest = format!("{:x}", hasher.finalize());
    digest[..TOOL_IDENTITY_DIGEST_HEX_BYTES].to_string()
}

fn canonical_name_available(
    tools: &BTreeMap<String, McpAgentTool>,
    exposed_name: &str,
    server_id: &str,
    tool_name: &str,
) -> Result<bool, String> {
    let Some(existing) = tools.get(exposed_name) else {
        return Ok(true);
    };
    if existing.server_id == server_id && existing.tool_name == tool_name {
        Ok(false)
    } else {
        Err("MCP exposed tool identity collision".to_string())
    }
}

fn resolve_exposed_tool<'a>(
    tools: &'a BTreeMap<String, McpAgentTool>,
    legacy_aliases: &BTreeMap<String, String>,
    name: &str,
) -> Option<&'a McpAgentTool> {
    tools.get(name).or_else(|| {
        legacy_aliases
            .get(name)
            .and_then(|canonical| tools.get(canonical))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exposed_names_are_readable_collision_safe_and_reversible() {
        let exposed = exposed_tool_name("server-a", "Desktop QA Echo", "repo/query");

        assert!(exposed.starts_with("mcp__desktop_qa_echo__repo_query__"));
        assert!(exposed.len() <= MAX_EXPOSED_TOOL_NAME_BYTES);
        assert!(exposed
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-')));
        assert_ne!(
            exposed,
            exposed_tool_name("server_a", "Desktop QA Echo", "repo-query")
        );
    }

    #[test]
    fn exposed_names_bound_untrusted_labels_without_losing_identity() {
        let server_id = "server-id";
        let server_name = format!("{} Ω", "Server".repeat(50));
        let tool_name = format!("{}-工具", "tool".repeat(45));

        let exposed = exposed_tool_name(server_id, &server_name, &tool_name);

        assert!(exposed.len() <= MAX_EXPOSED_TOOL_NAME_BYTES);
        assert!(exposed.starts_with("mcp__serverserver"));
        assert!(!exposed.contains('Ω'));
        assert!(!exposed.contains("工具"));
    }

    #[test]
    fn exposed_and_legacy_names_resolve_to_the_original_identity() {
        let server_id = "server-a";
        let server_name = "Desktop QA Echo";
        let tool_name = "repo/query";
        let canonical = exposed_tool_name(server_id, server_name, tool_name);
        let legacy = legacy_exposed_tool_name(server_id, tool_name);
        let tools = BTreeMap::from([(
            canonical.clone(),
            McpAgentTool {
                server_id: server_id.to_string(),
                server_name: server_name.to_string(),
                tool_name: tool_name.to_string(),
                definition: ToolDefinition::name_only(canonical.clone()),
                metadata: ToolMetadata {
                    name: canonical.clone(),
                    effect: ToolEffect::Read,
                    sensitive_input_fields: Default::default(),
                },
            },
        )]);
        let aliases = BTreeMap::from([(legacy.clone(), canonical)]);

        for exposed in [&legacy, tools.keys().next().expect("canonical name")] {
            let resolved = resolve_exposed_tool(&tools, &aliases, exposed).expect("mapped tool");
            assert_eq!(resolved.server_id, server_id);
            assert_eq!(resolved.tool_name, tool_name);
        }
    }

    #[test]
    fn invalid_discovered_tool_identifiers_are_rejected() {
        assert!(!valid_mcp_identifier(""));
        assert!(!valid_mcp_identifier("bad\ntool"));
        assert!(!valid_mcp_identifier(
            &"x".repeat(MAX_MCP_IDENTIFIER_BYTES + 1)
        ));
        assert!(valid_mcp_identifier(&"x".repeat(MAX_MCP_IDENTIFIER_BYTES)));
    }

    #[test]
    fn canonical_name_collision_fails_closed() {
        let exposed_name = "mcp__same__same__0123456789abcdef".to_string();
        let tools = BTreeMap::from([(
            exposed_name.clone(),
            McpAgentTool {
                server_id: "server-a".to_string(),
                server_name: "Same".to_string(),
                tool_name: "tool-a".to_string(),
                definition: ToolDefinition::name_only(exposed_name.clone()),
                metadata: ToolMetadata {
                    name: exposed_name.clone(),
                    effect: ToolEffect::Read,
                    sensitive_input_fields: Default::default(),
                },
            },
        )]);

        assert_eq!(
            canonical_name_available(&tools, &exposed_name, "server-a", "tool-a"),
            Ok(false)
        );
        assert!(canonical_name_available(&tools, &exposed_name, "server-b", "tool-b").is_err());
    }

    #[test]
    fn legacy_opaque_name_stays_stable_for_dispatch_compatibility() {
        assert_eq!(
            legacy_exposed_tool_name("server-a", "repo/query"),
            "mcp__c2VydmVyLWE__cmVwby9xdWVyeQ"
        );
    }

    #[test]
    fn model_aliases_accept_only_unambiguous_safe_names() {
        assert_eq!(model_alias_name(" local-echo "), Some("local-echo".into()));
        assert_eq!(
            model_alias_name("server_name-1"),
            Some("server_name-1".into())
        );
        assert_eq!(model_alias_name("server name"), None);
        assert_eq!(model_alias_name(""), None);
        assert_eq!(model_alias_name(&"x".repeat(65)), None);
    }

    #[test]
    fn conflicting_model_aliases_fail_closed() {
        let mut aliases = BTreeMap::new();
        insert_dispatch_alias(&mut aliases, "shared".into(), "canonical-a");
        insert_dispatch_alias(&mut aliases, "shared".into(), "canonical-b");

        assert_eq!(aliases.get("shared"), Some(&None));
    }

    #[test]
    fn allow_list_matches_only_declared_identity_or_wildcard() {
        assert!(server_allowed(Some(&["*".to_string()]), "id", "name"));
        assert!(server_allowed(Some(&["id".to_string()]), "id", "name"));
        assert!(!server_allowed(
            Some(&["another".to_string()]),
            "id",
            "name"
        ));
    }
}
