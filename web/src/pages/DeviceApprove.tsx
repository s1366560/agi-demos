/**
 * DeviceApprove Page — CLI device-code approval UI.
 *
 * Entry point: `/device` (optionally `/device?code=USERCODE`).
 * Used when a user runs `memstack login` on a terminal: they are sent
 * here to enter/confirm the 8-char user_code and approve the session.
 */

import React, { useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { Alert, Button, Card, Input, Result, Space, Typography } from 'antd';
import { Terminal } from 'lucide-react';

import { useAuthStore } from '@/stores/auth';

import { deviceAuthService } from '@/services/deviceAuthService';

import { confirmAction } from '@/utils/confirmAction';

import { getErrorMessage } from '@/types/common';

const { Title, Paragraph, Text } = Typography;

const CODE_LEN = 8;
const CODE_PATTERN = /^[A-Z0-9]{8}$/;

const normalize = (raw: string): string =>
  raw
    .replace(/[^a-zA-Z0-9]/g, '')
    .toUpperCase()
    .slice(0, CODE_LEN);

export const DeviceApprove: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const userEmail = useAuthStore((s) => s.user?.email ?? '');

  const [code, setCode] = useState<string>(() =>
    normalize(params.get('user_code') ?? params.get('code') ?? '')
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [approved, setApproved] = useState(false);

  if (!isAuthenticated) {
    // Normally unreachable: App.tsx guards /device with RedirectToLogin.
    // Kept as a defensive fallback so the shareable link can still be copied.
    const ret = `/device${code ? `?user_code=${code}` : ''}`;
    return (
      <div className="mx-auto my-16 max-w-[560px] p-6">
        <Card
          variant="borderless"
          className="rounded-md shadow-[0_0_0_1px_rgba(0,0,0,0.08)]"
        >
          <Space orientation="vertical" size="large" className="w-full">
            <Space orientation="vertical" size={4}>
              <Terminal size={28} strokeWidth={1.5} />
              <Title level={3} className="!m-0">
                {t('device.signInTitle')}
              </Title>
              <Paragraph type="secondary" className="!m-0">
                {t('device.signInSubtitle')}
              </Paragraph>
            </Space>
            <Text copyable={{ text: window.location.origin + ret }} type="secondary">
              {t('device.copyBackLink')}
            </Text>
          </Space>
        </Card>
      </div>
    );
  }

  const handleSubmit = async (): Promise<void> => {
    setError(null);
    const normalized = normalize(code);
    if (!CODE_PATTERN.test(normalized)) {
      setError(t('device.invalidCode'));
      return;
    }
    // Approving grants the waiting CLI a 30-day API key — confirm with the
    // exact code and account before minting anything.
    const confirmed = await confirmAction({
      title: t('device.confirmTitle', 'Approve CLI sign-in?'),
      content: t(
        'device.confirmContent',
        'Code {{code}} will receive a 30-day API key for {{email}}. Only approve if you just requested this code in your own terminal.',
        { code: normalized, email: userEmail }
      ),
      okText: t('device.approveSession', 'Approve CLI session'),
      cancelText: t('common.cancel'),
    });
    if (!confirmed) {
      return;
    }
    setSubmitting(true);
    try {
      await deviceAuthService.approve(normalized);
      setApproved(true);
    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setSubmitting(false);
    }
  };

  if (approved) {
    return (
      <div className="mx-auto my-16 max-w-[560px] p-6">
        <Result
          status="success"
          title={t('device.approvedTitle')}
          subTitle={t('device.approvedSubtitle')}
          extra={
            <Button type="primary" onClick={() => void navigate('/')}>
              {t('common.goHome')}
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="mx-auto my-16 max-w-[560px] p-6">
      <Card
        variant="borderless"
        className="rounded-md shadow-[0_0_0_1px_rgba(0,0,0,0.08)]"
      >
        <Space orientation="vertical" size="large" className="w-full">
          <Space orientation="vertical" size={4}>
            <Terminal size={28} strokeWidth={1.5} />
            <Title level={3} className="!m-0">
              {t('device.title')}
            </Title>
            <Paragraph type="secondary" className="!m-0">
              {t('device.subtitle')}
            </Paragraph>
          </Space>

          {error && <Alert type="error" title={error} showIcon />}

          <Alert
            type="info"
            showIcon
            title={t(
              'device.sessionInfo',
              'Approving as {{email}}. The waiting CLI will receive a 30-day API key for this account.',
              { email: userEmail }
            )}
          />

          <Space orientation="vertical" size={8} className="w-full">
            <label htmlFor="device-code-input">
              <Text strong>{t('device.codeLabel')}</Text>
            </label>
            <Input
              id="device-code-input"
              autoFocus
              size="large"
              placeholder={t('device.codePlaceholder')}
              value={code}
              maxLength={CODE_LEN}
              autoComplete="off"
              spellCheck={false}
              onChange={(e) => {
                setCode(normalize(e.target.value));
              }}
              onPressEnter={() => void handleSubmit()}
              className="font-mono text-xl tracking-[4px] text-center"
            />
          </Space>

          <Space className="w-full justify-end">
            <Button onClick={() => void navigate('/')}>{t('common.cancel')}</Button>
            <Button
              type="primary"
              loading={submitting}
              disabled={code.length !== CODE_LEN}
              onClick={() => void handleSubmit()}
            >
              {t('device.approveSession', 'Approve CLI session')}
            </Button>
          </Space>

          <Paragraph type="secondary" className="mt-2 !mb-0 text-xs">
            {t('device.footer')}
          </Paragraph>
        </Space>
      </Card>
    </div>
  );
};
