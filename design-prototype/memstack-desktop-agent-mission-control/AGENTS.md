# Prototype Instructions

Run the local server yourself and open the preview in the browser available to this environment. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's `get-context` skill when the visual source is unclear or no longer matches the current goal. When the user gives durable prototype-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

## Locked product direction

- Selected visual direction: `docs/product/desktop-agent-ui/visual-directions/02-my-work-mission-control.png`.
- Primary experience: My Work Mission Control — task queue on the left, active task inspection and artifact review on the right.
- The prototype must demonstrate both Work and Code modes through one shared task kernel.
- Preserve the selected mock's dark, dense, desktop-native visual language and cyan status accents.
- Every persisted task uses a plan-first creation flow: Describe task → Agent plans with read-only authority → Human reviews/edits → Approve & start. No execution state is implied before approval.
- Models, Skills, Plugins, and Agents live inside `Settings` under an `AI resources` section. Models is Provider-first: credentials and endpoints belong to Provider connections, discovered models are enabled separately, and workspace routing is a third policy layer. Skills, Plugins, and Agents keep the shared governed catalog/detail pattern.
- The prototype supports `en` and `zh-CN`. Language changes are immediate, persisted per device, update the document language, and must keep stable internal navigation/resource IDs independent from translated labels.
- Authentication begins before the mission-control shell. Settings is an independent modal window, and Tenant → Project context switching lives under Settings → Workspace rather than the global navigation.
- Resource creation starts as an auditable draft. Installing a plugin never grants it to an agent automatically; Agent capability assignment remains explicit.
