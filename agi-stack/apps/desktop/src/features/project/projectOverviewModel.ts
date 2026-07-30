import type {
  CloudProjectOverviewReadResult,
  CloudProjectOverviewScope,
  CloudProjectOverviewSnapshot,
} from './projectOverviewClient';

export type ProjectOverviewRequestAuthority = Readonly<{
  scope: CloudProjectOverviewScope;
  requestId: number;
}>;

export type ProjectOverviewError = Readonly<{
  code: string;
  message: string;
  retryable: boolean;
}>;

export type ProjectOverviewRetry = Readonly<{
  scope: CloudProjectOverviewScope;
  previousRequestId: number;
}>;

export type ProjectOverviewState = Readonly<{
  status: 'idle' | 'loading' | 'ready' | 'empty' | 'error';
  scope: CloudProjectOverviewScope | null;
  request: ProjectOverviewRequestAuthority | null;
  snapshot: CloudProjectOverviewSnapshot | null;
  error: ProjectOverviewError | null;
  retry: ProjectOverviewRetry | null;
}>;

export function emptyProjectOverviewState(): ProjectOverviewState {
  return {
    status: 'idle',
    scope: null,
    request: null,
    snapshot: null,
    error: null,
    retry: null,
  };
}

export function beginProjectOverviewRequest(
  request: ProjectOverviewRequestAuthority,
): ProjectOverviewState {
  return {
    status: 'loading',
    scope: request.scope,
    request,
    snapshot: null,
    error: null,
    retry: null,
  };
}

export function projectOverviewRequestIsCurrent(
  expected: ProjectOverviewRequestAuthority,
  current: ProjectOverviewState,
): boolean {
  return (
    current.request !== null &&
    current.request.requestId === expected.requestId &&
    sameProjectOverviewScope(current.request.scope, expected.scope) &&
    current.scope !== null &&
    sameProjectOverviewScope(current.scope, expected.scope)
  );
}

export function completeProjectOverviewRequest(
  current: ProjectOverviewState,
  request: ProjectOverviewRequestAuthority,
  result: CloudProjectOverviewReadResult,
): ProjectOverviewState {
  if (!projectOverviewRequestIsCurrent(request, current)) return current;
  if (result.kind === 'empty') {
    return {
      status: 'empty',
      scope: request.scope,
      request,
      snapshot: null,
      error: null,
      retry: retryAuthority(request),
    };
  }
  if (!sameProjectOverviewScope(result.snapshot.scope, request.scope)) return current;

  return {
    status: 'ready',
    scope: request.scope,
    request,
    snapshot: result.snapshot,
    error: null,
    retry: null,
  };
}

export function failProjectOverviewRequest(
  current: ProjectOverviewState,
  request: ProjectOverviewRequestAuthority,
  error: ProjectOverviewError,
): ProjectOverviewState {
  if (!projectOverviewRequestIsCurrent(request, current)) return current;

  return {
    status: 'error',
    scope: request.scope,
    request,
    snapshot: null,
    error,
    retry: error.retryable ? retryAuthority(request) : null,
  };
}

export function retryProjectOverviewRequest(
  current: ProjectOverviewState,
  request: ProjectOverviewRequestAuthority,
): ProjectOverviewState {
  if (
    current.retry === null ||
    !sameProjectOverviewScope(current.retry.scope, request.scope) ||
    !Number.isSafeInteger(request.requestId) ||
    request.requestId <= current.retry.previousRequestId
  ) {
    return current;
  }
  return beginProjectOverviewRequest(request);
}

function retryAuthority(
  request: ProjectOverviewRequestAuthority,
): ProjectOverviewRetry {
  return {
    scope: request.scope,
    previousRequestId: request.requestId,
  };
}

function sameProjectOverviewScope(
  left: CloudProjectOverviewScope,
  right: CloudProjectOverviewScope,
): boolean {
  return left.tenantId === right.tenantId && left.projectId === right.projectId;
}
