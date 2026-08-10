import type { AgentTimelineItem, DesktopApprovalRequest } from '../../types';

export type HitlDecisionOptionView = {
  value: string;
  label: string;
  description: string | null;
  recommended: boolean;
  riskLevel: string | null;
  estimatedTime: string | null;
  estimatedCost: string | null;
  risks: string[];
};

export type HitlDecisionView = {
  selectionMode: 'single' | 'multiple';
  maxSelections: number | null;
  allowCustom: boolean;
  defaultOption: string | null;
  options: HitlDecisionOptionView[];
};

export type HitlEnvVarFieldView = {
  name: string;
  label: string;
  description: string | null;
  required: boolean;
  secret: boolean;
  inputType: 'text' | 'password' | 'textarea' | 'url' | 'api_key' | 'file_path';
  inputElement: 'input' | 'password' | 'textarea' | 'url';
  placeholder: string | null;
};

export type HitlEnvVarView = {
  allowSave: boolean;
  fields: HitlEnvVarFieldView[];
};

export type HitlRequestExpiry = {
  state: 'none' | 'active' | 'expired' | 'invalid';
  expiresAt: string | null;
  remainingSeconds: number;
  canRespond: boolean;
};

export type BrowserOriginConsentView = {
  origin: string;
  tool: string | null;
  reason: string | null;
};

export type BrowserOriginConsentScope = 'once' | 'site' | 'all';

export type BrowserCapabilityConsentKind = 'browser_full_cdp' | 'browser_credential_fill';

export type BrowserCapabilityConsentView = BrowserOriginConsentView & {
  kind: BrowserCapabilityConsentKind;
};

export type BrowserFullCdpConsentScope = 'once' | 'site';

/**
 * Browser-origin consent detection (M2). The sidecar persists the agent's
 * permission HITL with `payload.decision` on the `permission_asked` timeline
 * item (target kind `browser_origin`, target id = origin host, action name =
 * gated browser tool). The decoded `approvalRequest.decision` is preferred
 * when the projection validated the full DecisionContext shape; the raw
 * payload is read loosely otherwise so the card still renders when the
 * agent supplied a partial context.
 */
export function browserOriginConsentView(
  item: AgentTimelineItem,
  approvalRequest: DesktopApprovalRequest | undefined,
): BrowserOriginConsentView | null {
  const view = browserConsentViewForKinds(item, approvalRequest, BROWSER_ORIGIN_TARGET_KINDS);
  return view ? { origin: view.origin, tool: view.tool, reason: view.reason } : null;
}

/**
 * Browser capability consent detection (M3). Same DecisionContext plumbing
 * as `browser_origin`, with target kind `browser_full_cdp` (elevated:
 * once/site scopes only, no all-sites) or `browser_credential_fill`
 * (vault-backed fill, once scope only). Target id remains the origin host.
 */
export function browserCapabilityConsentView(
  item: AgentTimelineItem,
  approvalRequest: DesktopApprovalRequest | undefined,
): BrowserCapabilityConsentView | null {
  return browserConsentViewForKinds(item, approvalRequest, BROWSER_CAPABILITY_TARGET_KINDS);
}

/** Browser-origin consent response contract: allow with once/site/all scopes. */
export function browserOriginAllowResponseData(
  scope: BrowserOriginConsentScope,
): Record<string, unknown> {
  return { action: 'allow', granted: true, scope };
}

/** Full-CDP consent response contract: allow with once/site scopes only. */
export function browserFullCdpAllowResponseData(
  scope: BrowserFullCdpConsentScope,
): Record<string, unknown> {
  return { action: 'allow', granted: true, scope };
}

/** Credential-fill consent response contract: allow once only. */
export function browserCredentialFillAllowResponseData(): Record<string, unknown> {
  return { action: 'allow', granted: true, scope: 'once' };
}

const BROWSER_ORIGIN_TARGET_KINDS = new Set(['browser_origin']);
const BROWSER_CAPABILITY_TARGET_KINDS = new Set<BrowserCapabilityConsentKind>([
  'browser_full_cdp',
  'browser_credential_fill',
]);

function browserConsentViewForKinds<K extends string>(
  item: AgentTimelineItem,
  approvalRequest: DesktopApprovalRequest | undefined,
  kinds: ReadonlySet<K>,
): (BrowserOriginConsentView & { kind: K }) | null {
  const payload = recordValue(item.payload);
  const decisions = [approvalRequest?.decision ?? null, recordValue(payload?.decision)];
  for (const decision of decisions) {
    if (!decision) continue;
    const target = recordValue(decision.target);
    const kind = firstString(target?.kind) as K | null;
    if (!target || !kind || !kinds.has(kind)) continue;
    const origin = firstString(target.id);
    if (!origin) continue;
    const action = recordValue(decision.action);
    return {
      kind,
      origin,
      tool: firstString(action?.name, payload?.tool, payload?.tool_name, item.toolName),
      reason: firstString(decision.reason, payload?.reason),
    };
  }
  return null;
}

const ENV_INPUT_TYPES = new Set<HitlEnvVarFieldView['inputType']>([
  'text',
  'password',
  'textarea',
  'url',
  'api_key',
  'file_path',
]);

export function hitlDecisionView(item: AgentTimelineItem): HitlDecisionView {
  const payload = recordValue(item.payload);
  const optionsSource = arrayValue(item.options) ?? arrayValue(payload?.options) ?? [];
  const options = uniqueBy(
    optionsSource.flatMap((candidate) => {
      const option = recordValue(candidate);
      if (!option) return [];
      const value = firstString(option.id, option.value, option.option_id);
      if (!value) return [];
      return [
        {
          value,
          label: firstString(option.label, option.title, option.name) ?? value,
          description: firstString(option.description, option.detail),
          recommended: option.recommended === true,
          riskLevel: firstString(option.risk_level, option.riskLevel),
          estimatedTime: firstString(option.estimated_time, option.estimatedTime),
          estimatedCost: firstString(option.estimated_cost, option.estimatedCost),
          risks: stringList(option.risks),
        },
      ];
    }),
    (option) => option.value,
  );
  const selectionMode =
    firstString(
      item.selectionMode,
      item.selection_mode,
      payload?.selection_mode,
      payload?.selectionMode,
    ) === 'multiple'
      ? 'multiple'
      : 'single';
  const rawMaxSelections = firstNumber(
    item.maxSelections,
    item.max_selections,
    payload?.max_selections,
    payload?.maxSelections,
  );
  const maxSelections =
    selectionMode === 'multiple' &&
    rawMaxSelections !== null &&
    Number.isInteger(rawMaxSelections) &&
    rawMaxSelections > 0
      ? rawMaxSelections
      : null;
  const defaultOption = firstString(
    item.defaultOption,
    item.default_option,
    payload?.default_option,
    payload?.defaultOption,
  );

  return {
    selectionMode,
    maxSelections,
    allowCustom:
      selectionMode === 'single' &&
      (firstBoolean(
        item.allowCustom,
        item.allow_custom,
        payload?.allow_custom,
        payload?.allowCustom,
      ) ??
        options.length === 0),
    defaultOption:
      defaultOption && options.some((option) => option.value === defaultOption)
        ? defaultOption
        : null,
    options,
  };
}

export function toggleDecisionSelection(
  current: readonly string[],
  optionValue: string,
  view: HitlDecisionView,
): string[] {
  if (!view.options.some((option) => option.value === optionValue)) return [...current];
  if (view.selectionMode === 'single') return [optionValue];
  if (current.includes(optionValue)) {
    return current.filter((candidate) => candidate !== optionValue);
  }
  if (view.maxSelections !== null && current.length >= view.maxSelections) {
    return [...current];
  }
  return [...current, optionValue];
}

export function buildDecisionResponse(
  selection: readonly string[],
  customSelected: boolean,
  customAnswer: string,
  view: HitlDecisionView,
): { decision: string | string[] } | null {
  const allowed = new Set(view.options.map((option) => option.value));
  const selected = [...new Set(selection)].filter((candidate) => allowed.has(candidate));
  if (view.selectionMode === 'multiple' && selected.length > 0) {
    return { decision: selected };
  }
  if (view.selectionMode === 'single' && !customSelected && selected.length > 0) {
    return { decision: selected[0] };
  }
  const custom = customAnswer.trim();
  return view.selectionMode === 'single' && view.allowCustom && customSelected && custom
    ? { decision: custom }
    : null;
}

export function hitlEnvVarView(item: AgentTimelineItem): HitlEnvVarView {
  const payload = recordValue(item.payload);
  const fieldsSource = arrayValue(item.fields) ?? arrayValue(payload?.fields) ?? [];
  const fields = uniqueBy(
    fieldsSource.flatMap((candidate) => {
      const field = recordValue(candidate);
      if (!field) return [];
      const name = firstString(field.name, field.key, field.variable);
      if (!name) return [];
      const requestedType = firstString(field.input_type, field.inputType);
      const inputType =
        requestedType && ENV_INPUT_TYPES.has(requestedType as HitlEnvVarFieldView['inputType'])
          ? (requestedType as HitlEnvVarFieldView['inputType'])
          : 'text';
      const secret = field.secret === true || inputType === 'password' || inputType === 'api_key';
      const inputElement: HitlEnvVarFieldView['inputElement'] =
        inputType === 'textarea'
          ? 'textarea'
          : inputType === 'url'
            ? 'url'
            : secret
              ? 'password'
              : 'input';
      const fieldView: HitlEnvVarFieldView = {
        name,
        label: firstString(field.label) ?? name,
        description: firstString(field.description),
        required: field.required !== false,
        secret,
        inputType,
        inputElement,
        placeholder: firstString(field.placeholder),
      };
      return [fieldView];
    }),
    (field) => field.name,
  );
  return {
    allowSave:
      firstBoolean(item.allowSave, item.allow_save, payload?.allow_save, payload?.allowSave) === true,
    fields,
  };
}

export function buildEnvVarResponse(
  values: Readonly<Record<string, string>>,
  save: boolean,
  view: HitlEnvVarView,
): { values: Record<string, string>; save: boolean } | null {
  const declaredValues = Object.fromEntries(
    view.fields.map((field) => [
      field.name,
      typeof values[field.name] === 'string' ? values[field.name] : '',
    ]),
  );
  if (
    view.fields.length === 0 ||
    view.fields.some((field) => field.required && !declaredValues[field.name]?.trim())
  ) {
    return null;
  }
  return { values: declaredValues, save: save && view.allowSave };
}

/**
 * Structured parameter preview for permission cards (P1-2). The backend
 * emits the tool input under `details` (`{tool, input}`) on the HITL record
 * and under `metadata.input` on the live `permission_asked` stream event, so
 * the preview reads whichever shape the timeline item carries. Read-only:
 * the permission response contract (`granted`/`action`/`scope`/`feedback`)
 * has no field for edited parameters.
 */
export function permissionParameterPreview(item: AgentTimelineItem): string | null {
  const payload = recordValue(item.payload);
  if (!payload) return null;
  const metadata = recordValue(payload.metadata);
  const details = recordValue(payload.details);
  const structured =
    firstRecord(details?.input, metadata?.input, payload.input, payload.arguments) ?? details;
  if (structured && Object.keys(structured).length > 0) {
    return formatPreviewValue(structured);
  }
  const command = firstString(payload.command, payload.cmd);
  return command ?? null;
}

function firstRecord(...values: unknown[]): Record<string, unknown> | null {
  for (const value of values) {
    const record = recordValue(value);
    if (record && Object.keys(record).length > 0) return record;
  }
  return null;
}

function formatPreviewValue(value: Record<string, unknown>): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return Object.keys(value).join(', ');
  }
}

export function hitlRequestExpiry(
  item: AgentTimelineItem,
  approvalRequest: DesktopApprovalRequest | undefined,
  nowMs: number,
): HitlRequestExpiry {
  const payload = recordValue(item.payload);
  const source =
    approvalRequest && Object.hasOwn(approvalRequest, 'expires_at')
      ? approvalRequest.expires_at
      : firstDefined(item.expires_at, item.expiresAt, payload?.expires_at, payload?.expiresAt);
  if (source === undefined || source === null) {
    return { state: 'none', expiresAt: null, remainingSeconds: 0, canRespond: true };
  }
  if (typeof source !== 'string' || !isRfc3339Timestamp(source)) {
    return {
      state: 'invalid',
      expiresAt: typeof source === 'string' ? source : null,
      remainingSeconds: 0,
      canRespond: false,
    };
  }
  const expiresAtMs = Date.parse(source);
  if (!Number.isFinite(expiresAtMs)) {
    return { state: 'invalid', expiresAt: source, remainingSeconds: 0, canRespond: false };
  }
  const remainingSeconds = Math.max(0, Math.ceil((expiresAtMs - nowMs) / 1000));
  return {
    state: remainingSeconds > 0 ? 'active' : 'expired',
    expiresAt: source,
    remainingSeconds,
    canRespond: remainingSeconds > 0,
  };
}

export function formatHitlRemaining(remainingSeconds: number): string {
  const total = Math.max(0, Math.floor(remainingSeconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return hours > 0
    ? `${hours}:${padTime(minutes)}:${padTime(seconds)}`
    : `${padTime(minutes)}:${padTime(seconds)}`;
}

function isRfc3339Timestamp(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value);
}

function padTime(value: number): string {
  return String(value).padStart(2, '0');
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function arrayValue(value: unknown): unknown[] | null {
  return Array.isArray(value) ? value : null;
}

function firstString(...values: unknown[]): string | null {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return null;
}

function firstNumber(...values: unknown[]): number | null {
  for (const value of values) {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return null;
}

function firstBoolean(...values: unknown[]): boolean | null {
  for (const value of values) {
    if (typeof value === 'boolean') return value;
  }
  return null;
}

function firstDefined(...values: unknown[]): unknown {
  return values.find((value) => value !== undefined);
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return [
    ...new Set(
      value.flatMap((candidate) => {
        const normalized = firstString(candidate);
        return normalized ? [normalized] : [];
      }),
    ),
  ];
}

function uniqueBy<T>(values: T[], key: (value: T) => string): T[] {
  const seen = new Set<string>();
  return values.filter((value) => {
    const identity = key(value);
    if (seen.has(identity)) return false;
    seen.add(identity);
    return true;
  });
}
