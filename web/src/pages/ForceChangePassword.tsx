import type React from 'react';
import { useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { Button, Form, Input, message, Typography } from 'antd';
import { Lock } from 'lucide-react';

import { useAuthStore } from '@/stores/auth';

import { authAPI } from '@/services/api';

const { Title, Text } = Typography;

interface ChangePasswordFormValues {
  currentPassword: string;
  newPassword: string;
  confirmPassword: string;
}

export const ForceChangePassword: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const setUser = useAuthStore((s) => s.setUser);
  const user = useAuthStore((s) => s.user);
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm<ChangePasswordFormValues>();

  const handleSubmit = async (values: ChangePasswordFormValues) => {
    setLoading(true);
    try {
      await authAPI.changePassword(values.currentPassword, values.newPassword);
      void message.success(t('forceChangePassword.success'));

      if (user) {
        setUser({ ...user, must_change_password: false });
      }

      navigate('/tenant', { replace: true });
    } catch (_error) {
      void message.error(t('forceChangePassword.failed'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-[#121520]">
      <div className="w-full max-w-md p-8 bg-white dark:bg-slate-900 rounded-2xl shadow-lg border border-gray-100 dark:border-slate-800">
        <div className="text-center mb-8">
          <div className="mx-auto w-12 h-12 flex items-center justify-center bg-blue-100 dark:bg-blue-900/30 rounded-full mb-4">
            <Lock size={20} className="text-blue-600 dark:text-blue-400" />
          </div>
          <Title level={3} className="!mb-1">
            {t('forceChangePassword.title')}
          </Title>
          <Text type="secondary">{t('forceChangePassword.subtitle')}</Text>
        </div>

        <Form<ChangePasswordFormValues>
          form={form}
          layout="vertical"
          onFinish={(values) => void handleSubmit(values)}
          autoComplete="off"
        >
          <Form.Item
            name="currentPassword"
            label={t('forceChangePassword.currentPassword')}
            rules={[
              {
                required: true,
                message: t('forceChangePassword.passwordRequired'),
              },
            ]}
          >
            <Input.Password
              placeholder={t('forceChangePassword.currentPasswordPlaceholder')}
              size="large"
            />
          </Form.Item>

          <Form.Item
            name="newPassword"
            label={t('forceChangePassword.newPassword')}
            rules={[
              {
                required: true,
                message: t('forceChangePassword.passwordRequired'),
              },
              {
                min: 8,
                message: t('forceChangePassword.passwordMinLength'),
              },
            ]}
          >
            <Input.Password
              placeholder={t('forceChangePassword.newPasswordPlaceholder')}
              size="large"
            />
          </Form.Item>

          <Form.Item
            name="confirmPassword"
            label={t('forceChangePassword.confirmPassword')}
            dependencies={['newPassword']}
            rules={[
              {
                required: true,
                message: t('forceChangePassword.passwordRequired'),
              },
              ({ getFieldValue }) => ({
                validator(_, value: string) {
                  if (!value || getFieldValue('newPassword') === value) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error(t('forceChangePassword.passwordMismatch')));
                },
              }),
            ]}
          >
            <Input.Password
              placeholder={t('forceChangePassword.confirmPasswordPlaceholder')}
              size="large"
            />
          </Form.Item>

          <Form.Item className="!mb-0 mt-6">
            <Button type="primary" htmlType="submit" loading={loading} block size="large">
              {loading ? t('forceChangePassword.loading') : t('forceChangePassword.submit')}
            </Button>
          </Form.Item>
        </Form>
      </div>
    </div>
  );
};
