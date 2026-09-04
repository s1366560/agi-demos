import type { TenantCreationInput, TenantCreationRecord } from './tenantCreationModel';

export type TenantCreationClient = Readonly<{
  create(
    input: TenantCreationInput,
    options?: Readonly<{ signal?: AbortSignal }>,
  ): Promise<TenantCreationRecord>;
}>;

export class TenantCreationError extends Error {
  readonly reasonCode: string;
  readonly status: number | null;

  constructor(reasonCode: string, status: number | null = null) {
    super(reasonCode);
    this.name = 'TenantCreationError';
    this.reasonCode = reasonCode;
    this.status = status;
  }
}
