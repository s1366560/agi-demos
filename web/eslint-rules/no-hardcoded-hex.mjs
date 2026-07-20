/**
 * @fileoverview Discourage hardcoded hex color literals in component code.
 *
 * Hex colors (`#fff`, `#38d6ff`, etc.) should come from design tokens
 * (`src/theme/tokens.ts` -> `@theme` CSS variables -> Tailwind utilities)
 * so that light/dark themes and brand palette stay in sync. This rule
 * flags raw hex literals appearing in string literals within `.tsx`/`.ts`
 * source files so new violations are caught at lint time.
 *
 * Allowed contexts (not flagged):
 *   - Hex inside CSS `var(--token, #fallback)` -- robust fallbacks are fine.
 *   - Hex passed as a fallback arg to theme-resolution utilities
 *     (resolveThemeColor, useThemeColor, resolveVar) alongside a `--token` arg.
 *   - Files in the allowList (theme tokens, antd theme, domain visualizations
 *     that require fixed color values: xterm terminal, graph nodes, 3D meshes,
 *     export renderers, color-picker palettes).
 */

/** Hex color regex: #RGB, #RGBA, #RRGGBB, #RRGGBBAA */
const HEX_RE = /#[0-9a-fA-F]{3,8}\b/;

/** Files whose hex literals are allowed by design. */
const ALLOW_LIST = [
  'src/theme/tokens.ts',
  'src/theme/antdTheme.ts',
  'src/index.css',
  'src/components/agent/sandbox/TerminalImpl.tsx',
  'src/components/graph/CytoscapeGraph/Config.ts',
  'src/components/graph/GraphVisualization.tsx',
  'src/components/workspace/hex3d/AgentMesh.tsx',
  'src/components/workspace/hex/HexCell.tsx',
  'src/components/workspace/hex/HexAgent.tsx',
  'src/components/agent/canvas/A2UISurfaceRenderer.tsx',
  'src/utils/exportConversation.ts',
  'src/components/blackboard/arrangementUtils.ts',
  'src/components/mcp-app/hostStyles.ts',
  'src/components/subagent/SubAgentModal.tsx',
];

/** Functions that resolve theme tokens with a hex fallback argument. */
const THEME_RESOLVER_FUNCS = new Set([
  'resolveThemeColor',
  'resolveVar',
  'useThemeColor',
  'useThemeColors',
]);

/** Strip hex values that appear inside a CSS var() fallback. */
function stripVarFallbacks(raw) {
  return raw.replace(/var\(([^()]*)\)/g, (match) => {
    const commaIdx = match.indexOf(',');
    if (commaIdx === -1) return match;
    return match.slice(0, commaIdx) + ')';
  });
}

/** Check if a node is a hex literal passed as fallback to a theme resolver. */
function isThemeResolverFallback(node) {
  // Walk up: Literal -> CallExpression(arg)
  const parent = node.parent;
  if (!parent || parent.type !== 'CallExpression') return false;
  const callee = parent.callee;
  const name =
    callee.type === 'Identifier' ? callee.name : callee.property?.name;
  if (!name || !THEME_RESOLVER_FUNCS.has(name)) return false;
  // Confirm a sibling arg is a CSS custom property reference (--color-...).
  return parent.arguments.some(
    (arg) =>
      arg.type === 'Literal' &&
      typeof arg.value === 'string' &&
      arg.value.includes('--color-'),
  );
}

function create(context) {
  const filename = context.filename || context.getFilename();
  const normalized = filename.replace(/\\/g, '/');

  if (ALLOW_LIST.some((p) => normalized.endsWith(p))) {
    return {};
  }

  function checkString(raw, node) {
    if (typeof raw !== 'string') return;
    const cleaned = stripVarFallbacks(raw);
    const match = HEX_RE.exec(cleaned);
    if (!match) return;
    if (isThemeResolverFallback(node)) return;
    context.report({
      node,
      message:
        'Avoid hardcoded hex color "{{hex}}". Use a design token ' +
        '(CSS variable / Tailwind utility) from src/theme/tokens.ts instead. ' +
        'If this is a domain-specific fixed color (terminal/graph/3D), add the ' +
        'file to the allowList in eslint-rules/no-hardcoded-hex.mjs.',
      data: { hex: match[0] },
    });
  }

  return {
    Literal(node) {
      if (typeof node.value === 'string') {
        checkString(node.value, node);
      }
    },
    TemplateElement(node) {
      if (node.value && typeof node.value.raw === 'string') {
        checkString(node.value.raw, node);
      }
    },
  };
}

export default {
  meta: {
    type: 'suggestion',
    docs: {
      description: 'Discourage hardcoded hex color literals in favor of design tokens.',
      recommended: false,
    },
    schema: [],
  },
  create,
};
