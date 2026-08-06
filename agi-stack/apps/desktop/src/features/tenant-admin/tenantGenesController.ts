import {
  createTenantManagementController,
  type TenantManagementControllerCore,
} from './tenantManagementController';
import type { TenantManagementScope } from './tenantManagementHttp';
import type { TenantGeneInput, TenantGenesClient } from './tenantGenesClient';
import {
  buildTenantGenesPresentation,
  type TenantGenesViewModel,
} from './tenantGenesPresentationModel';

export type TenantGenesController = TenantManagementControllerCore<
  TenantManagementScope,
  TenantGenesViewModel
> &
  Readonly<{
    createGene: (input: TenantGeneInput) => Promise<void>;
    updateGene: (geneId: string, input: Partial<TenantGeneInput>) => Promise<void>;
    deleteGene: (geneId: string) => Promise<void>;
    publishGene: (geneId: string) => Promise<void>;
    unpublishGene: (geneId: string) => Promise<void>;
    installGene: (instanceId: string, geneId: string) => Promise<void>;
    rateGene: (geneId: string, rating: number, comment?: string) => Promise<void>;
    createReview: (geneId: string, rating: number, content: string) => Promise<void>;
    deleteReview: (geneId: string, reviewId: string) => Promise<void>;
  }>;

export function createTenantGenesController({
  client,
  initialScope,
}: Readonly<{
  client: TenantGenesClient;
  initialScope: TenantManagementScope;
}>): TenantGenesController {
  const core = createTenantManagementController({
    initialScope,
    reasonPrefix: 'tenant_genes',
    loadAuthority: client.load,
    isEmpty: (data) => data.genes.length === 0,
    buildPresentation: buildTenantGenesPresentation,
  });
  return Object.freeze({
    ...core,
    createGene: (input) =>
      core.runAction('create', async (scope, signal) => {
        await client.createGene(scope, input, { signal });
      }),
    updateGene: (geneId, input) =>
      core.runAction('update', async (scope, signal) => {
        await client.updateGene(scope, geneId, input, { signal });
      }),
    deleteGene: (geneId) =>
      core.runAction('delete', (scope, signal) =>
        client.deleteGene(scope, geneId, { signal }),
      ),
    publishGene: (geneId) =>
      core.runAction('publish', async (scope, signal) => {
        await client.publishGene(scope, geneId, { signal });
      }),
    unpublishGene: (geneId) =>
      core.runAction('unpublish', async (scope, signal) => {
        await client.unpublishGene(scope, geneId, { signal });
      }),
    installGene: (instanceId, geneId) =>
      core.runAction('install', async (scope, signal) => {
        await client.installGene(scope, instanceId, geneId, { signal });
      }),
    rateGene: (geneId, rating, comment) =>
      core.runAction('rate', async (scope, signal) => {
        await client.rateGene(scope, geneId, rating, comment, { signal });
      }),
    createReview: (geneId, rating, content) =>
      core.runAction('create-review', async (scope, signal) => {
        await client.createReview(scope, geneId, rating, content, { signal });
      }),
    deleteReview: (geneId, reviewId) =>
      core.runAction('delete-own-review', (scope, signal) =>
        client.deleteReview(scope, geneId, reviewId, { signal }),
      ),
  });
}
