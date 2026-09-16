import React, { useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Alert, Checkbox, Modal, Space, Tag, Typography } from 'antd';

import { marketplacePackagePermissions } from '@/utils/pluginMarketplaceInstall';

import type { MarketplacePackageCatalogEntry } from '@/types/pluginMarketplace';

const { Text } = Typography;

interface InstallPluginPackageModalProps {
  readonly entry: MarketplacePackageCatalogEntry | null;
  readonly busy: boolean;
  readonly error: string | null;
  readonly onCancel: () => void;
  readonly onConfirm: () => void;
}

export const InstallPluginPackageModal: React.FC<InstallPluginPackageModalProps> = ({
  entry,
  busy,
  error,
  onCancel,
  onConfirm,
}) => {
  const { t } = useTranslation();
  const [scopeApproved, setScopeApproved] = useState(false);

  const permissions = entry ? marketplacePackagePermissions(entry.manifest) : [];

  return (
    <Modal
      open={entry !== null}
      title={
        entry
          ? t('tenant.pluginHub.pluginsList.confirmInstallNamed', {
              name: entry.plugin_id,
              version: entry.version,
            })
          : ''
      }
      okText={t('tenant.pluginHub.pluginsList.install')}
      cancelText={t('common.cancel')}
      okButtonProps={{ disabled: !scopeApproved }}
      confirmLoading={busy}
      onCancel={onCancel}
      onOk={onConfirm}
      destroyOnHidden
    >
      {entry ? (
        <Space orientation="vertical" size="middle" className="w-full">
          <Text type="secondary">{t('tenant.pluginHub.pluginsList.installDescriptionV2')}</Text>
          <div>
            <Text strong>{t('tenant.pluginHub.pluginsList.declaredPermissions')}</Text>
            <div className="mt-2">
              {permissions.length === 0 ? (
                <Text type="secondary">
                  {t('tenant.pluginHub.pluginsList.noDeclaredPermissions')}
                </Text>
              ) : (
                <Space wrap>
                  {permissions.map((permission) => (
                    <Tag key={permission}>{permission}</Tag>
                  ))}
                </Space>
              )}
            </div>
          </div>
          <Checkbox
            checked={scopeApproved}
            disabled={busy}
            onChange={(event) => { setScopeApproved(event.target.checked); }}
          >
            {t('tenant.pluginHub.pluginsList.approveTenantPermissions')}
          </Checkbox>
          {error ? <Alert type="error" showIcon title={error} data-testid="install-error" /> : null}
        </Space>
      ) : null}
    </Modal>
  );
};

export default InstallPluginPackageModal;
