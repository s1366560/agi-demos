import { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Select } from 'antd';

import { instanceService } from '@/services/instanceService';
import type { InstanceResponse } from '@/services/instanceService';

interface InstanceSelectProps {
  value?: string | undefined;
  onChange?: ((value: string | undefined) => void) | undefined;
  placeholder?: string | undefined;
  id?: string | undefined;
}

/**
 * Instance picker for install flows. Loads the tenant's instances on mount
 * and lets users pick one instead of hand-typing a raw instance UUID.
 * Value/onChange (and id) are injected by the wrapping antd Form.Item.
 */
export const InstanceSelect: React.FC<InstanceSelectProps> = ({
  value,
  onChange,
  placeholder,
  id,
}) => {
  const { t } = useTranslation();
  const [instances, setInstances] = useState<InstanceResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);

  useEffect(() => {
    let isCurrent = true;
    instanceService
      .list({ page: 1, page_size: 100 })
      .then((response) => {
        if (!isCurrent) return;
        setInstances(response.instances);
        setLoadFailed(false);
      })
      .catch(() => {
        if (!isCurrent) return;
        setLoadFailed(true);
      })
      .finally(() => {
        if (isCurrent) {
          setLoading(false);
        }
      });
    return () => {
      isCurrent = false;
    };
  }, []);

  return (
    <Select
      showSearch={{ optionFilterProp: 'label' }}
      allowClear
      loading={loading}
      placeholder={placeholder}
      notFoundContent={
        loadFailed
          ? t('tenant.genes.instanceLoadError', 'Failed to load instances')
          : t('tenant.genes.noInstances', 'No instances available')
      }
      options={instances.map((instance) => ({
        value: instance.id,
        label: `${instance.name} (${instance.slug})`,
      }))}
      {...(value !== undefined ? { value } : {})}
      {...(onChange ? { onChange } : {})}
      {...(id ? { id } : {})}
    />
  );
};
