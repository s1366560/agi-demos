import React from 'react';

import { useTranslation } from 'react-i18next';

import { GlobalOutlined } from '@ant-design/icons';

import { LazySelect } from '@/components/ui/lazyAntd';

export const LanguageSwitcher: React.FC = () => {
  const { i18n } = useTranslation();

  const handleChange = (value: string) => {
    i18n.changeLanguage(value);
  };

  return (
    <LazySelect
      defaultValue={i18n.language || 'en-US'}
      value={i18n.language}
      onChange={handleChange}
      style={{ width: 120 }}
      suffixIcon={<GlobalOutlined />}
      options={[
        { value: 'en-US', label: 'English' },
        { value: 'zh-CN', label: '简体中文' },
      ]}
    />
  );
};
