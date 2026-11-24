import { useState } from 'react';

import { RichPackagePages } from '../../../../packages/plugin-marketplace-ui/src/RichPackagePages';
import { useI18n } from '../i18nContext';
import { transport, streamCommand } from './transport';

export function TenantPackagePage({ tenantId, segment }: { tenantId: string; segment: string }) {
  const { locale, t } = useI18n();
  const base = '/tenant/' + encodeURIComponent(tenantId);
  const [pathname, navigate] = useState(base + '/' + segment);
  return (
    <RichPackagePages
      scope={{ tenantId, projectId: null }}
      target="desktop-renderer"
      locale={locale}
      pathname={pathname}
      transport={transport}
      streamCommand={streamCommand}
      navigate={navigate}
      backToMarket={<a href={'#' + base + '/plugins?marketScope=tenant'}>{t('nav.plugins')}</a>}
    />
  );
}
