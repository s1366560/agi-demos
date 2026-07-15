# Desktop Model Provider Settings Design QA

## Verdict

- P0: none.
- P1: none.
- P2: none after the provider-kind, catalog-filtering, and unsupported-probe fixes.
- P3: the implementation uses live tenant/provider data, so the provider names and empty model catalog differ from the prototype's illustrative rows. This is authoritative content, not structural drift.

## Comparison setup

- Source visual truth: `/Users/tiejunsun/github/agi-demos/design-prototype/memstack-desktop-agent-mission-control`
- Implementation URL: `http://127.0.0.1:5173/`
- Viewport: 1280 x 720.
- State: dark mode, authenticated, Settings -> Models -> Provider Overview.
- Source screenshot: `/tmp/memstack-goal-audit-20260715/07-prototype-model-settings-current.png`
- Implementation screenshot: `/tmp/memstack-goal-audit-20260715/08-implementation-model-settings-final.png`
- Focused source provider detail: `/tmp/memstack-goal-audit-20260715/11-prototype-provider-detail.png`
- Focused implementation provider detail: `/tmp/memstack-goal-audit-20260715/12-implementation-provider-detail.png`
- Provider wizard step 1: `/tmp/memstack-goal-audit-20260715/13-implementation-provider-wizard-step1.png`
- Provider wizard step 3: `/tmp/memstack-goal-audit-20260715/14-implementation-provider-wizard-step3.png`

The source and implementation screenshots were opened together at the same viewport before the final verdict. Modal geometry, three-column composition, header, sidebar, provider list, detail hierarchy, tabs, cards, spacing, typography, borders, and color treatment match closely.

## Primary interactions verified

- Open Settings as an independent modal window and navigate to Models.
- List only LLM providers; embedding and rerank providers no longer appear in this workspace.
- Select a provider and switch among Overview, Connection, Models, Routing, and Usage tabs.
- Edit an existing API-key provider without revealing or resending the stored secret.
- Validate an unchanged existing connection through the persisted-provider health endpoint.
- Open the add-provider wizard and choose a supported cloud or local runtime.
- Confirm unsupported Azure OpenAI, Bedrock, and Vertex types are hidden until provider-specific probes exist.
- Validate an Ollama draft against a local runtime before continuing.
- Confirm the primary discovered model is selected and cannot be deselected.
- Close the wizard without creating test data.
- Browser console errors: none.

## Comparison history

1. Initial comparison found an embedding provider in the LLM settings list, unsupported provider types exposed in the wizard, and a misleading provider-kind label.
2. The UI was changed to filter non-LLM operations, require `probe_supported`, and derive cloud/local labeling from the authentication contract.
3. Post-fix comparison shows four authoritative LLM providers, supported-only wizard choices, correct cloud/local labels, and a real validation gate before model selection.
4. Connection editing was hardened so endpoint/provider changes require a new key, while an unchanged endpoint can validate with the encrypted stored credential.
5. Final browser flow completed with zero console errors and no remaining P0/P1/P2 visual or interaction findings.

final result: passed
