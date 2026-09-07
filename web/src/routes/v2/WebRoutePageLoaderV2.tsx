import type { FC } from 'react';

import { useTranslation } from 'react-i18next';

import { Spinner } from '../../components/common/Spinner';

export const WebRoutePageLoaderV2: FC = () => {
  const { t } = useTranslation();
  return (
    <div className="flex items-center justify-center h-50" role="status">
      <Spinner size={32} />
      <span className="sr-only">{t('common.loading', 'Loading…')}</span>
    </div>
  );
};
