import type { TenantSummary } from '../../types';

export const TENANT_CREATION_PLANS = Object.freeze([
  'free',
  'basic',
  'premium',
  'enterprise',
] as const);

export type TenantCreationPlan = (typeof TENANT_CREATION_PLANS)[number];

export type TenantCreationDraft = Readonly<{
  name: string;
  description: string;
  plan: TenantCreationPlan;
}>;

export type TenantCreationInput = TenantCreationDraft;

export type TenantCreationRecord = Readonly<
  Required<
    Pick<
      TenantSummary,
      | 'id'
      | 'name'
      | 'slug'
      | 'description'
      | 'owner_id'
      | 'plan'
      | 'created_at'
      | 'updated_at'
    >
  > & {
    max_projects: number;
    max_users: number;
    max_storage: number;
  }
>;

export type TenantCreationValidation =
  | Readonly<{ valid: true; value: TenantCreationInput }>
  | Readonly<{
      valid: false;
      reasonCode:
        | 'tenant_creation_name_required'
        | 'tenant_creation_name_too_long'
        | 'tenant_creation_description_too_long'
        | 'tenant_creation_plan_invalid';
    }>;

export function createTenantCreationDraft(): TenantCreationDraft {
  return Object.freeze({
    name: '',
    description: '',
    plan: 'free',
  });
}

export function validateTenantCreationDraft(
  draft: Readonly<{
    name: string;
    description: string;
    plan: string;
  }>,
): TenantCreationValidation {
  const name = draft.name.trim();
  const description = draft.description.trim();
  if (!name) {
    return Object.freeze({
      valid: false,
      reasonCode: 'tenant_creation_name_required',
    });
  }
  if (name.length > 255) {
    return Object.freeze({
      valid: false,
      reasonCode: 'tenant_creation_name_too_long',
    });
  }
  if (description.length > 1000) {
    return Object.freeze({
      valid: false,
      reasonCode: 'tenant_creation_description_too_long',
    });
  }
  if (!isTenantCreationPlan(draft.plan)) {
    return Object.freeze({
      valid: false,
      reasonCode: 'tenant_creation_plan_invalid',
    });
  }
  return Object.freeze({
    valid: true,
    value: Object.freeze({
      name,
      description,
      plan: draft.plan,
    }),
  });
}

export function tenantCreationIsDirty(draft: TenantCreationDraft): boolean {
  return Boolean(
    draft.name.trim() ||
      draft.description.trim() ||
      draft.plan !== 'free',
  );
}

export function upsertCreatedTenant(
  tenants: readonly TenantSummary[],
  created: TenantCreationRecord,
): readonly TenantSummary[] {
  const next = [...tenants];
  const index = next.findIndex((tenant) => tenant.id === created.id);
  if (index === -1) next.push(created);
  else next[index] = created;
  return Object.freeze(next);
}

export function isTenantCreationPlan(
  value: string,
): value is TenantCreationPlan {
  return (TENANT_CREATION_PLANS as readonly string[]).includes(value);
}
