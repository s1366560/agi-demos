export type DeadLetterQueueAuthority = 'cloud' | 'local';

export type DeadLetterQueueScope = Readonly<{
  authority: DeadLetterQueueAuthority;
  tenantId: string;
}>;

export type DeadLetterQueueMessageStatus =
  | 'pending'
  | 'retrying'
  | 'discarded'
  | 'expired'
  | 'resolved';

export type DeadLetterQueueQuery = Readonly<{
  status?: DeadLetterQueueMessageStatus | 'all';
  eventType?: string;
  errorType?: string;
  routingKey?: string;
  limit?: number;
  offset?: number;
}>;

export type DeadLetterQueueMessage = Readonly<{
  id: string;
  eventId: string;
  eventType: string;
  eventData: string;
  routingKey: string;
  error: string;
  errorType: string;
  errorTraceback: string | null;
  retryCount: number;
  maxRetries: number;
  firstFailedAt: string;
  lastFailedAt: string;
  nextRetryAt: string | null;
  status: DeadLetterQueueMessageStatus;
  metadata: Readonly<Record<string, unknown>>;
  canRetry: boolean;
  ageSeconds: number;
}>;

export type DeadLetterQueueStats = Readonly<{
  totalMessages: number;
  pendingCount: number;
  retryingCount: number;
  discardedCount: number;
  expiredCount: number;
  resolvedCount: number;
  oldestMessageAgeSeconds: number;
  errorTypeCounts: Readonly<Record<string, number>>;
  eventTypeCounts: Readonly<Record<string, number>>;
}>;

export type DeadLetterQueuePage = Readonly<{
  scope: DeadLetterQueueScope;
  authority: DeadLetterQueueAuthority;
  availability: 'available';
  reasonCode: null;
  serviceVersion: string;
  contractVersion: string;
  allowedActions: readonly string[];
  authorityRevision: number | null;
  messages: readonly DeadLetterQueueMessage[];
  total: number;
  limit: number;
  offset: number;
  hasMore: boolean;
}>;

export type DeadLetterQueueBatchResult = Readonly<{
  results: Readonly<Record<string, boolean>>;
  successCount: number;
  failureCount: number;
}>;

export type DeadLetterQueueCleanupResult = Readonly<{ cleanedCount: number }>;

export type DeadLetterQueueRequestOptions = Readonly<{ signal?: AbortSignal }>;

export type DeadLetterQueueClient = Readonly<{
  listMessages: (
    scope: DeadLetterQueueScope,
    query?: DeadLetterQueueQuery,
    options?: DeadLetterQueueRequestOptions,
  ) => Promise<DeadLetterQueuePage>;
  getMessage: (
    scope: DeadLetterQueueScope,
    messageId: string,
    options?: DeadLetterQueueRequestOptions,
  ) => Promise<DeadLetterQueueMessage>;
  getStats: (
    scope: DeadLetterQueueScope,
    options?: DeadLetterQueueRequestOptions,
  ) => Promise<DeadLetterQueueStats>;
  retryMessage: (
    scope: DeadLetterQueueScope,
    messageId: string,
    options?: DeadLetterQueueRequestOptions,
  ) => Promise<void>;
  retryMessages: (
    scope: DeadLetterQueueScope,
    messageIds: readonly string[],
    options?: DeadLetterQueueRequestOptions,
  ) => Promise<DeadLetterQueueBatchResult>;
  discardMessage: (
    scope: DeadLetterQueueScope,
    messageId: string,
    reason: string,
    options?: DeadLetterQueueRequestOptions,
  ) => Promise<void>;
  discardMessages: (
    scope: DeadLetterQueueScope,
    messageIds: readonly string[],
    reason: string,
    options?: DeadLetterQueueRequestOptions,
  ) => Promise<DeadLetterQueueBatchResult>;
  cleanupExpired: (
    scope: DeadLetterQueueScope,
    olderThanHours: number,
    options?: DeadLetterQueueRequestOptions,
  ) => Promise<DeadLetterQueueCleanupResult>;
  cleanupResolved: (
    scope: DeadLetterQueueScope,
    olderThanHours: number,
    options?: DeadLetterQueueRequestOptions,
  ) => Promise<DeadLetterQueueCleanupResult>;
}>;

export class DeadLetterQueueUnavailableError extends Error {
  readonly reasonCode: string;

  constructor(reasonCode: string) {
    super(reasonCode);
    this.name = 'DeadLetterQueueUnavailableError';
    this.reasonCode = reasonCode;
  }
}
