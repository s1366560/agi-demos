import {
  RuntimeV2Error,
  type GenerationLeaseV2,
  type RuntimeGenerationV2,
  type ScopeV2,
} from '@agistack/plugin-runtime';

export type DesktopRendererServiceOperationLeaseRequestV2 = Readonly<{
  service: string;
  scope: ScopeV2;
  version?: string;
  isolation?: string;
}>;

export type DesktopRendererServiceOperationLeaseAdmissionV2<TService> =
  | Readonly<{
      status: 'accepted';
      digest: string;
      useService: <TResult>(operation: (service: TService) => TResult) => TResult;
      acquireChildServiceLease?: <TChild>(
        request: DesktopRendererServiceOperationLeaseRequestV2,
      ) => Promise<DesktopRendererServiceOperationLeaseAdmissionV2<TChild>>;
      release: () => Promise<void>;
    }>
  | Readonly<{
      status: 'rejected';
      reasonCode:
        | 'desktop_renderer_service_request_invalid'
        | 'desktop_renderer_service_generation_required'
        | 'desktop_renderer_service_generation_digest_missing'
        | 'desktop_renderer_service_generation_lease_acquire_failed'
        | 'desktop_renderer_service_resolve_failed';
      runtimeCode?: string;
    }>;

type DesktopRendererServiceOperationLeaseRejectionReasonV2 = Extract<
  DesktopRendererServiceOperationLeaseAdmissionV2<never>,
  { status: 'rejected' }
>['reasonCode'];

const REQUEST_KEYS_V2 = new Set(['isolation', 'scope', 'service', 'version']);
const SCOPE_KEYS_V2 = new Set(['kind', 'project_id', 'session_id', 'tenant_id']);
const SCOPE_KINDS_V2 = new Set(['project', 'root', 'session', 'tenant']);

export async function acquireDesktopRendererServiceOperationLeaseV2<TService>(
  generation: RuntimeGenerationV2 | undefined,
  request: DesktopRendererServiceOperationLeaseRequestV2,
  acquireGenerationLease: (generation: RuntimeGenerationV2) => GenerationLeaseV2,
): Promise<DesktopRendererServiceOperationLeaseAdmissionV2<TService>> {
  const frozenRequest = cloneServiceOperationRequestV2(request);
  if (frozenRequest === undefined) {
    return rejectServiceOperationLeaseV2('desktop_renderer_service_request_invalid');
  }
  if (generation === undefined) {
    return rejectServiceOperationLeaseV2('desktop_renderer_service_generation_required');
  }
  const digest = generation.snapshot.digest.trim();
  if (!digest) {
    return rejectServiceOperationLeaseV2('desktop_renderer_service_generation_digest_missing');
  }

  let leaseCandidate: unknown;
  try {
    leaseCandidate = acquireGenerationLease(generation);
  } catch (error) {
    return rejectServiceOperationLeaseV2(
      'desktop_renderer_service_generation_lease_acquire_failed',
      error,
    );
  }
  if (!isGenerationLeaseV2(leaseCandidate)) {
    return rejectServiceOperationLeaseV2(
      'desktop_renderer_service_generation_lease_acquire_failed',
    );
  }
  const lease = leaseCandidate;

  let service: TService;
  try {
    service = generation.resolve<TService>(frozenRequest.service, frozenRequest.scope, {
      isolation: frozenRequest.isolation,
      version: frozenRequest.version,
    });
  } catch (error) {
    await consumeGenerationLeaseReleaseV2(lease);
    return rejectServiceOperationLeaseV2('desktop_renderer_service_resolve_failed', error);
  }

  let released = false;
  let releasePromise: Promise<void> | undefined;
  // Older release-only adapters remain valid, but cannot grant a generation-bound child lease.
  const fork =
    lease.generation === generation && typeof lease.fork === 'function'
      ? lease.fork.bind(lease)
      : undefined;
  return Object.freeze({
    digest,
    ...(fork === undefined
      ? {}
      : {
          acquireChildServiceLease: <TChild>(
            childRequest: DesktopRendererServiceOperationLeaseRequestV2,
          ): Promise<DesktopRendererServiceOperationLeaseAdmissionV2<TChild>> => {
            if (released) {
              return Promise.resolve(
                rejectServiceOperationLeaseV2(
                  'desktop_renderer_service_generation_lease_acquire_failed',
                  new RuntimeV2Error(
                    'generation_lease_released',
                    'parent service lease is released',
                  ),
                ),
              );
            }
            return acquireDesktopRendererServiceOperationLeaseV2<TChild>(
              generation,
              childRequest,
              () => fork(),
            );
          },
        }),
    release: () => {
      if (releasePromise === undefined) {
        released = true;
        releasePromise = releaseGenerationLeaseV2(lease);
      }
      return releasePromise;
    },
    status: 'accepted' as const,
    useService: <TResult>(operation: (resolvedService: TService) => TResult): TResult => {
      if (released) {
        throw new Error('desktop_renderer_service_generation_lease_released');
      }
      return operation(service);
    },
  });
}

function cloneServiceOperationRequestV2(
  value: unknown,
): DesktopRendererServiceOperationLeaseRequestV2 | undefined {
  if (!isRecordV2(value) || !hasOnlyKeysV2(value, REQUEST_KEYS_V2)) return undefined;
  if (!isCanonicalStringV2(value.service)) return undefined;
  if (value.version !== undefined && !isCanonicalStringV2(value.version)) return undefined;
  if (value.isolation !== undefined && !isCanonicalStringV2(value.isolation)) return undefined;
  const scope = cloneServiceOperationScopeV2(value.scope);
  if (scope === undefined) return undefined;
  return Object.freeze({
    service: value.service,
    scope,
    ...(value.version === undefined ? {} : { version: value.version }),
    ...(value.isolation === undefined ? {} : { isolation: value.isolation }),
  });
}

function cloneServiceOperationScopeV2(
  value: unknown,
): DesktopRendererServiceOperationLeaseRequestV2['scope'] | undefined {
  if (!isRecordV2(value) || !hasOnlyKeysV2(value, SCOPE_KEYS_V2)) return undefined;
  if (typeof value.kind !== 'string' || !SCOPE_KINDS_V2.has(value.kind)) return undefined;
  for (const key of ['project_id', 'session_id', 'tenant_id'] as const) {
    const identifier = value[key];
    if (identifier !== undefined && identifier !== null && !isCanonicalStringV2(identifier)) {
      return undefined;
    }
  }
  return Object.freeze({
    kind: value.kind as DesktopRendererServiceOperationLeaseRequestV2['scope']['kind'],
    ...(value.tenant_id === undefined ? {} : { tenant_id: value.tenant_id as string | null }),
    ...(value.project_id === undefined ? {} : { project_id: value.project_id as string | null }),
    ...(value.session_id === undefined ? {} : { session_id: value.session_id as string | null }),
  });
}

function rejectServiceOperationLeaseV2<TService>(
  reasonCode: DesktopRendererServiceOperationLeaseRejectionReasonV2,
  error?: unknown,
): DesktopRendererServiceOperationLeaseAdmissionV2<TService> {
  if (error instanceof RuntimeV2Error) {
    return Object.freeze({ reasonCode, runtimeCode: error.code, status: 'rejected' });
  }
  return Object.freeze({ reasonCode, status: 'rejected' });
}

function releaseGenerationLeaseV2(lease: GenerationLeaseV2): Promise<void> {
  return Promise.resolve().then(() => lease.release());
}

async function consumeGenerationLeaseReleaseV2(lease: GenerationLeaseV2): Promise<void> {
  try {
    await releaseGenerationLeaseV2(lease);
  } catch {
    // The primary resolve failure remains authoritative for admission.
  }
}

function isRecordV2(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function hasOnlyKeysV2(value: Record<string, unknown>, allowed: ReadonlySet<string>): boolean {
  return Object.keys(value).every((key) => allowed.has(key));
}

function isGenerationLeaseV2(value: unknown): value is GenerationLeaseV2 {
  return isRecordV2(value) && typeof value.release === 'function';
}

function isCanonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}
