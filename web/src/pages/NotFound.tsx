/**
 * NotFound Page — catch-all 404 for unmatched routes.
 *
 * Mounted as the `*` fallback route in App.tsx.
 */

import React from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { Button, Result } from 'antd';

export const NotFound: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <Result
        status="404"
        title={t('notFound.title', 'Page not found')}
        subTitle={t(
          'notFound.subtitle',
          'The page you are looking for does not exist or has been moved.'
        )}
        extra={
          <Button type="primary" onClick={() => void navigate('/')}>
            {t('common.goHome', 'Go home')}
          </Button>
        }
      />
    </div>
  );
};
