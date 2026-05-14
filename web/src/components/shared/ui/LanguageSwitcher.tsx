import type React from 'react';

import { useTranslation } from 'react-i18next';

import { Globe } from 'lucide-react';

import { LazySelect } from '@/components/ui/lazyAntd';
import { authAPI } from '@/services/api';
import { useAuthStore } from '@/stores/auth';

export const LanguageSwitcher: React.FC = () => {
  const { i18n } = useTranslation();
  const user = useAuthStore((state) => state.user);
  const setUser = useAuthStore((state) => state.setUser);

  const handleChange = (value: string) => {
    void i18n.changeLanguage(value);
    if (user && (value === 'en-US' || value === 'zh-CN')) {
      // Best-effort persistence. Failures don't block the UI switch.
      authAPI
        .updatePreferredLanguage(value)
        .then((updated) => {
          setUser(updated);
        })
        .catch(() => {
          /* swallow: local i18n already updated */
        });
    }
  };

  return (
    <LazySelect
      defaultValue={i18n.language || 'en-US'}
      value={i18n.language}
      onChange={handleChange}
      style={{ width: 120 }}
      suffixIcon={<Globe size={16} />}
      options={[
        { value: 'en-US', label: 'English' },
        { value: 'zh-CN', label: '简体中文' }, // i18n-ignore: native script convention
      ]}
    />
  );
};
