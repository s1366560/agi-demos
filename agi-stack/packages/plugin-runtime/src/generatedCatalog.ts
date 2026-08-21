// Generated from shared/schemas/plugins/platform-plugin-protocol.v2.schema.json.
// Schema SHA-256: 04c5cbd66568e7eb5ea3929409589c2f53fcb91079ec9a9ad077448c2839aadf
// Do not edit by hand; run scripts/generate_plugin_protocol_v2.py.

import type { PluginContractV2 } from './generated';

export interface PluginModuleCatalogEntryV2 {
  readonly artifact_digest: string;
  readonly contract: PluginContractV2;
  readonly contract_digest: string;
  readonly entrypoint: string;
  readonly module_ref: string;
  readonly plugin_id: string;
  readonly plugin_version: string;
  readonly targets: ReadonlyArray<string>;
}

export interface PluginModuleCatalogV2 {
  readonly catalog_digest: string;
  readonly modules: ReadonlyArray<PluginModuleCatalogEntryV2>;
  readonly schema_version: 2;
}

export const PLUGIN_MODULE_CATALOG_V2_JSON = [
  '{"catalog_digest":"sha256:335aff27bc2a2f139e8e14c609eeeb982ed54871ace97390efff17fcaa',
  'c4dae5","modules":[{"artifact_digest":"sha256:e273d03e1b5a1ac9af8b21a4b43e750043a49a',
  'ff05abee41e0d41b3da76351fc","contract":{"config_schema":{"$schema":"https://json-sch',
  'ema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"strategy":',
  '{"const":"explicit-id","type":"string"}},"required":["strategy"],"type":"object"},"e',
  'vents":{"emits":[],"handles":[]},"services":{"provides":[{"service":"service:agent-d',
  'efinition-resolver","version":"1.0.0"}],"requires":[]}},"contract_digest":"sha256:f9',
  '9de77f9e769cfcd7b94c22638ebd23d17e74decf0b6a9b9a0f995f2b510163","entrypoint":"src.in',
  'frastructure.plugins.v2.agent_definition:_apply_agent_definition_resolver_v2","modul',
  'e_ref":"builtin://memstack/agent/definition","plugin_id":"memstack-runtime-kernel","',
  'plugin_version":"2.0.0","targets":["python"]},{"artifact_digest":"sha256:93425e44167',
  'aea4e1cbe718606ee2115183f45126e56a7c77ba33ff6f4cd286e","contract":{"config_schema":{',
  '"$schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":fals',
  'e,"properties":{"loop_id":{"const":"builtin-react","type":"string"}},"required":["lo',
  'op_id"],"type":"object"},"events":{"emits":[],"handles":[]},"services":{"provides":[',
  '{"service":"service:agent-loop-resolver","version":"1.0.0"}],"requires":[]}},"contra',
  'ct_digest":"sha256:0bee827149f227522c61182c7095c1dd4a92f30e1408c1717f48cb42162a1ae1"',
  ',"entrypoint":"src.infrastructure.plugins.v2.agent_loop:_apply_builtin_agent_loop_v2',
  '","module_ref":"builtin://memstack/agent/loop","plugin_id":"memstack-runtime-kernel"',
  ',"plugin_version":"2.0.0","targets":["python"]},{"artifact_digest":"sha256:40cce8ce0',
  'c0c4bc39f5887cb28b330ffbbb0660acc7f37c39c40807b55eecb1e","contract":{"config_schema"',
  ':{"$schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":fa',
  'lse,"properties":{"strategy":{"const":"system-prompt-manager","type":"string"}},"req',
  'uired":["strategy"],"type":"object"},"events":{"emits":[],"handles":[]},"services":{',
  '"provides":[{"service":"service:system-prompt-builder","version":"1.0.0"}],"requires',
  '":[]}},"contract_digest":"sha256:dfb15d8704512a2930e6603cc771779bf285a4990fa223bffd1',
  '716d763fedf5f","entrypoint":"src.infrastructure.plugins.v2.system_prompt:_apply_syst',
  'em_prompt_builder_v2","module_ref":"builtin://memstack/agent/system-prompt","plugin_',
  'id":"memstack-runtime-kernel","plugin_version":"2.0.0","targets":["python"]},{"artif',
  'act_digest":"sha256:e168f18efecdcad3ad499cd6bc8e4cb70a9b276263c1cd13e305b83d458ccd7b',
  '","contract":{"config_schema":{"$schema":"https://json-schema.org/draft/2020-12/sche',
  'ma","additionalProperties":false,"properties":{"strategy":{"const":"dynamic-agent-to',
  'ols","type":"string"}},"required":["strategy"],"type":"object"},"events":{"emits":[]',
  ',"handles":[]},"services":{"provides":[{"service":"service:tool-set-resolver","versi',
  'on":"1.0.0"}],"requires":[]}},"contract_digest":"sha256:8e57e4aea3b75d17385298345892',
  '17af77df8dfed1e0a653b582d801b4c4ae1f","entrypoint":"src.infrastructure.plugins.v2.to',
  'ol_set:_apply_tool_set_resolver_v2","module_ref":"builtin://memstack/agent/tool-set"',
  ',"plugin_id":"memstack-runtime-kernel","plugin_version":"2.0.0","targets":["python"]',
  '},{"artifact_digest":"sha256:aa58e3be49786a1f2123f6f2e2eee3f9de1e676cfd490a2bfa4dc73',
  '11a90b204","contract":{"config_schema":{"$schema":"https://json-schema.org/draft/202',
  '0-12/schema","additionalProperties":false,"properties":{"routes":{"items":{"addition',
  'alProperties":false,"properties":{"authorization_mode":{"minLength":1,"type":"string',
  '"},"enabled":{"type":"boolean"},"method":{"pattern":"^[A-Z]+$","type":"string"},"pat',
  'h":{"pattern":"^/","type":"string"},"permission":{"minLength":1,"type":"string"},"pl',
  'ugin_id":{"minLength":1,"type":"string"}},"required":["authorization_mode","enabled"',
  ',"method","path","permission","plugin_id"],"type":"object"},"type":"array"}},"requir',
  'ed":["routes"],"type":"object"},"events":{"emits":[],"handles":[]},"services":{"prov',
  'ides":[],"requires":[{"alias":"route_table","service":"service:http.route-table-buil',
  'der","version":"1.0.0"}]}},"contract_digest":"sha256:0e16c9f6154395c3a4ce95aab8f31a5',
  '3e21b41a5607e7a03d6a80696f327640d","entrypoint":"src.infrastructure.plugins.v2.legac',
  'y_http_route_bridge:legacy_http_route_bridge_definition_v2","module_ref":"builtin://',
  'memstack/http/legacy-route-bridge","plugin_id":"memstack-runtime-kernel","plugin_ver',
  'sion":"2.0.0","targets":["python"]},{"artifact_digest":"sha256:7de45bd69889fe515f1e1',
  '736ac44de22952363d5d926d0fabebdd8ce8995f60c","contract":{"config_schema":{"$schema":',
  '"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"propert',
  'ies":{},"type":"object"},"events":{"emits":[],"handles":[]},"services":{"provides":[',
  '{"service":"service:http.route-table-builder","version":"1.0.0"}],"requires":[]}},"c',
  'ontract_digest":"sha256:d8478b3b7a7100a0984d71a56373d0d9b76bdca8d56510b077bfed1f336e',
  '8d86","entrypoint":"src.infrastructure.plugins.v2.route_effects:route_table_builder_',
  'definition_v2","module_ref":"builtin://memstack/http/route-table-builder","plugin_id',
  '":"memstack-runtime-kernel","plugin_version":"2.0.0","targets":["python"]},{"artifac',
  't_digest":"sha256:26a9f8ac163ef161009d7138809ef602fda88585a9bb404677d797b105158dc6",',
  '"contract":{"config_schema":{"$schema":"https://json-schema.org/draft/2020-12/schema',
  '","additionalProperties":false,"properties":{"strategy":{"const":"required-agent-too',
  'l-call","type":"string"}},"required":["strategy"],"type":"object"},"events":{"emits"',
  ':[],"handles":[]},"services":{"provides":[{"service":"service:plugin-selection-judge',
  '","version":"1.0.0"}],"requires":[]}},"contract_digest":"sha256:7f7ceeb21dcef0999b7f',
  'd0d38d675e52eb41f0fbafb37e0165e8a66751ddbe1b","entrypoint":"src.infrastructure.plugi',
  'ns.v2.selection_judge:_apply_plugin_selection_judge_v2","module_ref":"builtin://mems',
  'tack/plugins/selection-judge","plugin_id":"memstack-runtime-kernel","plugin_version"',
  ':"2.0.0","targets":["python"]},{"artifact_digest":"sha256:5b577e0c8be69c0807c332bdbb',
  'eddf6e6e40d92a1127c599b734aec3da67a17f","contract":{"config_schema":{"$schema":"http',
  's://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":',
  '{"protocol_version":{"const":2,"type":"integer"}},"required":["protocol_version"],"t',
  'ype":"object"},"events":{"emits":[],"handles":[]},"services":{"provides":[{"service"',
  ':"service:runtime-generation-boundary","version":"1.0.0"}],"requires":[]}},"contract',
  '_digest":"sha256:4252d589a33fc7cea6ababb8703c365ea8fc56cdfa825ed58b84ce5c6e798979","',
  'entrypoint":"src.infrastructure.plugins.v2.builtin_modules:_apply_runtime_boundary",',
  '"module_ref":"builtin://memstack/runtime/generation-boundary","plugin_id":"memstack-',
  'runtime-kernel","plugin_version":"2.0.0","targets":["python"]},{"artifact_digest":"s',
  'ha256:b5d32e313b41bd898961e189cd8e36ab7704d23baad6dcc8ee84f266fae0a434","contract":{',
  '"config_schema":{"$schema":"https://json-schema.org/draft/2020-12/schema","additiona',
  'lProperties":false,"properties":{"strategy":{"const":"ordered-sql-event-log","type":',
  '"string"}},"required":["strategy"],"type":"object"},"events":{"emits":[],"handles":[',
  ']},"services":{"provides":[{"service":"service:session-event-log","version":"1.0.0"}',
  '],"requires":[]}},"contract_digest":"sha256:081387f06d341da12450daedda2583999da04ae1',
  '34406a5f5c7804dcc64f0b9c","entrypoint":"src.infrastructure.plugins.v2.session_event_',
  'log:_apply_session_event_log_v2","module_ref":"builtin://memstack/session/event-log"',
  ',"plugin_id":"memstack-runtime-kernel","plugin_version":"2.0.0","targets":["python"]',
  '}],"schema_version":2}\n',
].join('');

export const PLUGIN_MODULE_CATALOG_V2 = JSON.parse(
  PLUGIN_MODULE_CATALOG_V2_JSON
) as PluginModuleCatalogV2;

export const PLUGIN_MODULE_CATALOG_DIGEST_V2 =
  'sha256:335aff27bc2a2f139e8e14c609eeeb982ed54871ace97390efff17fcaac4dae5' as const;
