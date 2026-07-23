/**
 * Shared i18n key + fallback maps for marketplace entity (gene / genome) actions.
 *
 * GeneDetail and GenomeDetail historically kept two parallel copies of the
 * publish/delete/rate/install flows whose only differences were the i18n key
 * prefixes and per-entity wording. The shared marketplace components resolve
 * their copy through this map so the pages only pass the entity kind and an
 * action set. Fallbacks mirror the strings the pages rendered before the
 * extraction.
 */

export type MarketplaceEntityKind = 'gene' | 'genome';

interface MarketplaceCopyEntry {
  key: string;
  fallback: string;
}

interface MarketplaceEntityCopy {
  /** "Unpublish {{name}}?" confirm dialog */
  unpublishConfirmTitle: MarketplaceCopyEntry;
  unpublishConfirmContent: MarketplaceCopyEntry;
  publishSuccess: MarketplaceCopyEntry;
  unpublishSuccess: MarketplaceCopyEntry;
  publishError: MarketplaceCopyEntry;
  unpublishError: MarketplaceCopyEntry;
  /** "Delete {{name}}?" confirm dialog */
  deleteConfirmTitle: MarketplaceCopyEntry;
  deleteConfirmContent: MarketplaceCopyEntry;
  deleteSuccess: MarketplaceCopyEntry;
  deleteError: MarketplaceCopyEntry;
  /** Install modal */
  installTitle: MarketplaceCopyEntry;
  installSuccess: MarketplaceCopyEntry;
  installError: MarketplaceCopyEntry;
  configOverrideTooltip: MarketplaceCopyEntry;
  configOverridePlaceholder: MarketplaceCopyEntry;
  /** Rate modal */
  rateTitle: MarketplaceCopyEntry;
  rateSuccess: MarketplaceCopyEntry;
  rateError: MarketplaceCopyEntry;
}

const GENE_COPY: MarketplaceEntityCopy = {
  unpublishConfirmTitle: {
    key: 'tenant.genes.unpublishConfirmTitle',
    fallback: 'Unpublish {{name}}?',
  },
  unpublishConfirmContent: {
    key: 'tenant.genes.unpublishConfirmContent',
    fallback: 'This removes the gene from the public marketplace. Installed copies keep working.',
  },
  publishSuccess: { key: 'tenant.genes.publishSuccess', fallback: 'Gene published successfully' },
  unpublishSuccess: {
    key: 'tenant.genes.unpublishSuccess',
    fallback: 'Gene unpublished successfully',
  },
  publishError: { key: 'tenant.genes.publishError', fallback: 'Failed to publish gene' },
  unpublishError: { key: 'tenant.genes.unpublishError', fallback: 'Failed to unpublish gene' },
  deleteConfirmTitle: { key: 'tenant.genes.deleteConfirmTitle', fallback: 'Delete {{name}}?' },
  deleteConfirmContent: {
    key: 'tenant.genes.deleteConfirmContent',
    fallback: 'This removes the gene from the marketplace and cannot be undone.',
  },
  deleteSuccess: { key: 'tenant.genes.deleteSuccess', fallback: 'Gene deleted successfully' },
  deleteError: { key: 'tenant.genes.deleteError', fallback: 'Failed to delete gene' },
  installTitle: { key: 'tenant.genes.installGene', fallback: 'Install Gene' },
  installSuccess: { key: 'tenant.genes.installSuccess', fallback: 'Gene installed successfully' },
  installError: { key: 'tenant.genes.installError', fallback: 'Failed to install gene' },
  configOverrideTooltip: {
    key: 'tenant.genes.configOverrideTooltip',
    fallback: 'Optional JSON config applied on top of the gene defaults',
  },
  configOverridePlaceholder: {
    key: 'tenant.genes.configOverridePlaceholder',
    fallback: '{"key": "value"}',
  },
  rateTitle: { key: 'tenant.genes.rateGene', fallback: 'Rate Gene' },
  rateSuccess: { key: 'tenant.genes.rateSuccess', fallback: 'Rating submitted successfully' },
  rateError: { key: 'tenant.genes.rateError', fallback: 'Failed to submit rating' },
};

const GENOME_COPY: MarketplaceEntityCopy = {
  unpublishConfirmTitle: {
    key: 'tenant.genomeDetail.unpublishConfirmTitle',
    fallback: 'Unpublish {{name}}?',
  },
  unpublishConfirmContent: {
    key: 'tenant.genomeDetail.unpublishConfirmContent',
    fallback: 'This removes the genome from the public marketplace. Installed copies keep working.',
  },
  publishSuccess: {
    key: 'tenant.genomeDetail.publishSuccess',
    fallback: 'Genome published successfully',
  },
  unpublishSuccess: {
    key: 'tenant.genomeDetail.unpublishSuccess',
    fallback: 'Genome unpublished successfully',
  },
  publishError: { key: 'tenant.genomeDetail.publishError', fallback: 'Failed to publish genome' },
  unpublishError: {
    key: 'tenant.genomeDetail.unpublishError',
    fallback: 'Failed to unpublish genome',
  },
  deleteConfirmTitle: {
    key: 'tenant.genomeDetail.deleteConfirmTitle',
    fallback: 'Delete {{name}}?',
  },
  deleteConfirmContent: {
    key: 'tenant.genomeDetail.deleteConfirmContent',
    fallback: 'This removes the genome from the marketplace and cannot be undone.',
  },
  deleteSuccess: {
    key: 'tenant.genomeDetail.deleteSuccess',
    fallback: 'Genome deleted successfully',
  },
  deleteError: { key: 'tenant.genomeDetail.deleteError', fallback: 'Failed to delete genome' },
  installTitle: { key: 'tenant.genomeDetail.installGenome', fallback: 'Install Genome' },
  installSuccess: {
    key: 'tenant.genomeDetail.installSuccess',
    fallback: 'Genome installed successfully',
  },
  installError: { key: 'tenant.genomeDetail.installError', fallback: 'Failed to install genome' },
  configOverrideTooltip: {
    key: 'tenant.genomeDetail.installConfigTooltip',
    fallback:
      'Optional JSON config applied to the genome install. Use gene slugs as keys for per-gene config.',
  },
  configOverridePlaceholder: {
    key: 'tenant.genomeDetail.configOverridePlaceholder',
    fallback: '{"key": "value"}',
  },
  rateTitle: { key: 'tenant.genomeDetail.rateGenome', fallback: 'Rate Genome' },
  rateSuccess: {
    key: 'tenant.genomeDetail.rateSuccess',
    fallback: 'Genome rating submitted successfully',
  },
  rateError: {
    key: 'tenant.genomeDetail.rateError',
    fallback: 'Failed to submit genome rating',
  },
};

export const marketplaceEntityCopy = (kind: MarketplaceEntityKind): MarketplaceEntityCopy =>
  kind === 'gene' ? GENE_COPY : GENOME_COPY;
