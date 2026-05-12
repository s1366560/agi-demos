import type { GeneResponse } from '@/services/geneMarketService';
import type { GenePayload } from './GeneEditorModal';
import type { CyberGeneCategory } from '@/types/workspace';

const KNOWN_CATEGORIES: ReadonlySet<CyberGeneCategory> = new Set([
  'skill',
  'knowledge',
  'tool',
  'workflow',
]);

const normalizeCategory = (raw: string | null | undefined): CyberGeneCategory => {
  if (!raw) return 'skill';
  const lower = raw.toLowerCase();
  if (KNOWN_CATEGORIES.has(lower as CyberGeneCategory)) {
    return lower as CyberGeneCategory;
  }
  return 'skill';
};

/**
 * Translate a marketplace `Gene` into a workspace `CyberGene` payload draft.
 *
 * Marketplace `manifest` is a free-form object; we serialize it as the
 * workspace gene's `config_json` so the editor can present and refine it.
 * The user can then adjust fields before saving.
 */
export const marketplaceGeneToPayload = (
  gene: GeneResponse
): Partial<GenePayload> => {
  return {
    name: gene.name,
    category: normalizeCategory(gene.category),
    description: gene.description ?? null,
    config_json: JSON.stringify(gene.manifest ?? {}, null, 2),
    version: gene.version,
    is_active: true,
  };
};
