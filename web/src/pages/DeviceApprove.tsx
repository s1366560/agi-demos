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
      <div style={{ maxWidth: 560, margin: '64px auto', padding: 24 }}>
        <Card
          variant="borderless"
          style={{ boxShadow: '0 0 0 1px rgba(0,0,0,0.08)', borderRadius: 6 }}
        >
          <Space orientation="vertical" size="large" style={{ width: '100%' }}>
            <Space orientation="vertical" size={4}>
              <Terminal size={28} strokeWidth={1.5} />
              <Title level={3} style={{ margin: 0 }}>
                {t('device.signInTitle')}
              </Title>
              <Paragraph type="secondary" style={{ margin: 0 }}>
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
      <div style={{ maxWidth: 560, margin: '64px auto', padding: 24 }}>
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
    <div style={{ maxWidth: 560, margin: '64px auto', padding: 24 }}>
      <Card
        variant="borderless"
        style={{ boxShadow: '0 0 0 1px rgba(0,0,0,0.08)', borderRadius: 6 }}
      >
        <Space orientation="vertical" size="large" style={{ width: '100%' }}>
          <Space orientation="vertical" size={4}>
            <Terminal size={28} strokeWidth={1.5} />
            <Title level={3} style={{ margin: 0 }}>
              {t('device.title')}
            </Title>
            <Paragraph type="secondary" style={{ margin: 0 }}>
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

          <Space orientation="vertical" size={8} style={{ width: '100%' }}>
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
              style={{
                fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
                fontSize: 20,
                letterSpacing: 4,
                textAlign: 'center',
              }}
            />
          </Space>

          <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
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

          <Paragraph type="secondary" style={{ fontSize: 12, marginTop: 8, marginBottom: 0 }}>
            {t('device.footer')}
          </Paragraph>
        </Space>
      </Card>
    </div>
  );
};
