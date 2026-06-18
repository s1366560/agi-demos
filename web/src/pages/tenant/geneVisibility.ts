import type { ContentVisibilityValue } from '../../services/geneMarketService';
import type { TFunction } from 'i18next';

export const visibilityOptions = (
  t: TFunction
): Array<{ value: ContentVisibilityValue; label: string }> => [
  { value: 'public', label: t('tenant.genes.filters.visPublic', 'Public') },
  { value: 'org_private', label: t('tenant.genes.filters.visPrivate', 'Private') },
  { value: 'unlisted', label: t('tenant.genes.filters.visUnlisted', 'Unlisted') },
];

export const visibilityLabel = (visibility: ContentVisibilityValue, t: TFunction): string => {
  const option = visibilityOptions(t).find((item) => item.value === visibility);
  return option?.label ?? visibility;
};

export const visibilityTagColor = (visibility: ContentVisibilityValue): string => {
  const colors: Record<ContentVisibilityValue, string> = {
    public: 'green',
    org_private: 'red',
    unlisted: 'default',
  };
  return colors[visibility];
};
