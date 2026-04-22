/**
 * DeviceApprove Page — CLI device-code approval UI.
 *
 * Entry point: `/device` (optionally `/device?code=ABCD1234`).
 * Used when a user runs `memstack login` on a terminal: they are sent
 * here to enter/confirm the 8-char user_code and approve the session.
 */

import React, { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { Alert, Button, Card, Input, Result, Space, Typography } from 'antd';
import { Terminal, CheckCircle2 } from 'lucide-react';

import { useAuthStore } from '@/stores/auth';

import { deviceAuthService } from '@/services/deviceAuthService';

import { getErrorMessage } from '@/types/common';

const { Title, Paragraph, Text } = Typography;

const CODE_LEN = 8;
const CODE_PATTERN = /^[A-Z0-9]{8}$/;

const normalize = (raw: string): string =>
  raw.replace(/[^a-zA-Z0-9]/g, '').toUpperCase().slice(0, CODE_LEN);

export const DeviceApprove: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  const [code, setCode] = useState<string>(() =>
    normalize(params.get('user_code') ?? params.get('code') ?? '')
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [approved, setApproved] = useState(false);

  useEffect(() => {
    // No auto-redirect: App.tsx doesn't support a post-login return URL.
    // If unauthenticated we render an inline prompt below.
  }, []);

  if (!isAuthenticated) {
    const ret = `/device${code ? `?code=${code}` : ''}`;
    return (
      <div style={{ maxWidth: 560, margin: '64px auto', padding: 24 }}>
        <Card
          bordered={false}
          style={{ boxShadow: '0 0 0 1px rgba(0,0,0,0.08)', borderRadius: 6 }}
        >
          <Space direction="vertical" size="large" style={{ width: '100%' }}>
            <Space direction="vertical" size={4}>
              <Terminal size={28} strokeWidth={1.5} />
              <Title level={3} style={{ margin: 0 }}>
                {t('device.signInTitle', 'Sign in to continue')}
              </Title>
              <Paragraph type="secondary" style={{ margin: 0 }}>
                {t(
                  'device.signInSubtitle',
                  'You must be signed in to approve a CLI login. After signing in, reopen this link from your terminal.'
                )}
              </Paragraph>
            </Space>
            <Space>
              <Button type="primary" onClick={() => navigate('/login')}>
                {t('common.signIn', 'Sign in')}
              </Button>
              <Text copyable={{ text: window.location.origin + ret }} type="secondary">
                {t('device.copyBackLink', 'Copy return link')}
              </Text>
            </Space>
          </Space>
        </Card>
      </div>
    );
  }

  const handleSubmit = async (): Promise<void> => {
    setError(null);
    const normalized = normalize(code);
    if (!CODE_PATTERN.test(normalized)) {
      setError(
        t('device.invalidCode', 'Enter the 8-character code shown in your terminal.')
      );
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
          icon={<CheckCircle2 size={56} color="#0070f3" strokeWidth={1.5} />}
          status="success"
          title={t('device.approvedTitle', 'Device approved')}
          subTitle={t(
            'device.approvedSubtitle',
            'Your terminal should be signed in. You can close this tab.'
          )}
          extra={
            <Button type="primary" onClick={() => navigate('/')}>
              {t('common.goHome', 'Go home')}
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 560, margin: '64px auto', padding: 24 }}>
      <Card
        bordered={false}
        style={{ boxShadow: '0 0 0 1px rgba(0,0,0,0.08)', borderRadius: 6 }}
      >
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <Space direction="vertical" size={4}>
            <Terminal size={28} strokeWidth={1.5} />
            <Title level={3} style={{ margin: 0 }}>
              {t('device.title', 'Connect a device')}
            </Title>
            <Paragraph type="secondary" style={{ margin: 0 }}>
              {t(
                'device.subtitle',
                'Enter the 8-character code shown in your terminal to grant access.'
              )}
            </Paragraph>
          </Space>

          {error && <Alert type="error" message={error} showIcon />}

          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <Text strong>{t('device.codeLabel', 'Device code')}</Text>
            <Input
              autoFocus
              size="large"
              placeholder="ABCD1234"
              value={code}
              maxLength={CODE_LEN}
              onChange={(e) => setCode(normalize(e.target.value))}
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
            <Button onClick={() => navigate('/')}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button
              type="primary"
              loading={submitting}
              disabled={code.length !== CODE_LEN}
              onClick={() => void handleSubmit()}
            >
              {t('device.approve', 'Approve')}
            </Button>
          </Space>

          <Paragraph
            type="secondary"
            style={{ fontSize: 12, marginTop: 8, marginBottom: 0 }}
          >
            {t(
              'device.footer',
              'Only approve codes you just generated yourself. A 30-day API key will be issued to the waiting CLI.'
            )}
          </Paragraph>
        </Space>
      </Card>
    </div>
  );
};
