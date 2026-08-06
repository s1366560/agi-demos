import {
  createTenantManagementController,
  type TenantManagementControllerCore,
} from './tenantManagementController';
import type { TenantManagementScope } from './tenantManagementHttp';
import type {
  TenantWebhook,
  TenantWebhookInput,
  TenantWebhooksClient,
} from './tenantWebhooksClient';
import {
  buildTenantWebhooksPresentation,
  type TenantWebhooksViewModel,
} from './tenantWebhooksPresentationModel';

export type TenantWebhooksController = TenantManagementControllerCore<
  TenantManagementScope,
  TenantWebhooksViewModel
> &
  Readonly<{
    createWebhook: (input: TenantWebhookInput) => Promise<TenantWebhook>;
    updateWebhook: (
      webhookId: string,
      input: TenantWebhookInput & Readonly<{ isActive: boolean }>,
    ) => Promise<void>;
    deleteWebhook: (webhookId: string) => Promise<void>;
    copySecret: (secret: string) => Promise<void>;
  }>;

export function createTenantWebhooksController({
  client,
  initialScope,
}: Readonly<{
  client: TenantWebhooksClient;
  initialScope: TenantManagementScope;
}>): TenantWebhooksController {
  const core = createTenantManagementController({
    initialScope,
    reasonPrefix: 'tenant_webhooks',
    loadAuthority: client.load,
    isEmpty: (data) => data.webhooks.length === 0,
    buildPresentation: buildTenantWebhooksPresentation,
  });
  return Object.freeze({
    ...core,
    async createWebhook(input) {
      let created: TenantWebhook | null = null;
      await core.runAction('create', async (scope, signal) => {
        created = await client.createWebhook(scope, input, { signal });
      });
      if (!created) throw new Error('tenant_webhooks_create_result_unavailable');
      return created;
    },
    updateWebhook: (webhookId, input) =>
      core.runAction('update', async (scope, signal) => {
        await client.updateWebhook(scope, webhookId, input, { signal });
      }),
    deleteWebhook: (webhookId) =>
      core.runAction('delete', (scope, signal) =>
        client.deleteWebhook(scope, webhookId, { signal }),
      ),
    async copySecret(secret) {
      await navigator.clipboard.writeText(secret);
    },
  });
}
