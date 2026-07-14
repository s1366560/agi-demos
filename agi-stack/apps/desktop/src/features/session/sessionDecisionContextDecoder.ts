import type { DecisionContext } from '../../types';

export function decodeDecisionContext(value: unknown): DecisionContext | null {
  const decision = recordValue(value);
  const action = decision ? recordValue(decision.action) : null;
  const target = decision ? recordValue(decision.target) : null;
  const data = decision ? recordValue(decision.data) : null;
  const risk = decision ? recordValue(decision.risk) : null;
  const reversibility = decision ? recordValue(decision.reversibility) : null;
  const scope = decision ? recordValue(decision.scope) : null;
  const evidence = decision ? readEvidenceArray(decision.evidence) : null;
  if (
    !decision ||
    !action ||
    typeof action.name !== 'string' ||
    typeof action.label !== 'string' ||
    !target ||
    typeof target.kind !== 'string' ||
    typeof target.id !== 'string' ||
    !optionalString(target.version_id) ||
    !optionalString(target.path) ||
    !data ||
    typeof data.summary !== 'string' ||
    (data.redacted_fields !== undefined && !stringArray(data.redacted_fields)) ||
    typeof decision.reason !== 'string' ||
    !risk ||
    !['low', 'medium', 'high'].includes(String(risk.level)) ||
    typeof risk.rationale !== 'string' ||
    !reversibility ||
    !['reversible', 'partial', 'irreversible'].includes(String(reversibility.mode)) ||
    !optionalString(reversibility.recovery) ||
    !scope ||
    typeof scope.kind !== 'string' ||
    !stringArray(scope.ids) ||
    !evidence
  ) {
    return null;
  }
  return decision as DecisionContext;
}

function readEvidenceArray(value: unknown): DecisionContext['evidence'] | null {
  if (!Array.isArray(value)) return null;
  const result: DecisionContext['evidence'] = [];
  for (const item of value) {
    const evidence = recordValue(item);
    if (
      !evidence ||
      typeof evidence.kind !== 'string' ||
      typeof evidence.id !== 'string' ||
      typeof evidence.label !== 'string' ||
      !optionalString(evidence.uri) ||
      !optionalString(evidence.digest)
    ) {
      return null;
    }
    result.push(evidence as DecisionContext['evidence'][number]);
  }
  return result;
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function optionalString(value: unknown): boolean {
  return value === undefined || value === null || typeof value === 'string';
}

function stringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}
