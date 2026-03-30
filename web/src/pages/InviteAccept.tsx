/**
 * InviteAccept Page - Invitation acceptance handler
 *
 * Handles the invitation acceptance flow:
 * 1. Extracts token from URL params
 * 2. Validates invitation token via backend API
 * 3. Shows invitation details (workspace, inviter, role)
 * 4. Handles accept/decline actions
 * 5. Redirects to login if not authenticated
 *
 * @module pages/InviteAccept
 */

import React, { useEffect, useState, useCallback } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';

import { Alert, Button, Card, Result, Skeleton, Space, Typography } from 'antd';
import { CheckCircle2, XCircle, Mail } from 'lucide-react';

import { useAuthStore } from '@/stores/auth';

import { invitationService, type InvitationVerifyResponse } from '@/services/invitationService';

import { getErrorMessage } from '@/types/common';

const { Title, Text, Paragraph } = Typography;

/**
 * Page states for the invitation acceptance flow
 */
type PageState = 'loading' | 'valid' | 'invalid' | 'expired' | 'accepting' | 'accepted' | 'error';

/**
 * Invitation details from verification response
 */
interface InvitationDetails {
  email: string;
  tenantId: string;
  role: string;
  expiresAt: string;
}

/**
 * InviteAccept Component
 *
 * Handles invitation acceptance flow with token validation,
 * authentication check, and workspace joining.
 */
export const InviteAccept: React.FC = () => {
  const { t } = useTranslation();
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();

  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const user = useAuthStore((state) => state.user);

  const [pageState, setPageState] = useState<PageState>('loading');
  const [invitationDetails, setInvitationDetails] = useState<InvitationDetails | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Current URL for redirect after login
  const currentPath = typeof window !== 'undefined' ? window.location.pathname : '';

  /**
   * Verify the invitation token on mount
   */
  useEffect(() => {
    const verifyToken = async () => {
      if (!token) {
        setPageState('invalid');
        setErrorMessage(t('inviteAccept.errors.missingToken', 'Invitation token is missing'));
        return;
      }

      try {
        const response: InvitationVerifyResponse = await invitationService.verify(token);

        if (!response.valid) {
          setPageState('invalid');
          setErrorMessage(t('inviteAccept.errors.invalidToken', 'This invitation is invalid'));
          return;
        }

        // Check if invitation has expired
        if (response.expires_at) {
          const expiresAt = new Date(response.expires_at);
          if (expiresAt < new Date()) {
            setPageState('expired');
            return;
          }
        }

        setInvitationDetails({
          email: response.email ?? '',
          tenantId: response.tenant_id ?? '',
          role: response.role ?? 'member',
          expiresAt: response.expires_at ?? '',
        });
        setPageState('valid');
      } catch (error) {
        setPageState('error');
        setErrorMessage(
          getErrorMessage(error) ??
            t('inviteAccept.errors.verifyFailed', 'Failed to verify invitation')
        );
      }
    };

    verifyToken();
  }, [token, t]);

  /**
   * Handle invitation acceptance
   */
  const handleAccept = useCallback(async () => {
    if (!token || !isAuthenticated) {
      return;
    }

    setPageState('accepting');
    setErrorMessage(null);

    try {
      await invitationService.accept(token);
      setPageState('accepted');
    } catch (error) {
      setPageState('error');
      const msg = getErrorMessage(error);
      setErrorMessage(msg ?? t('inviteAccept.errors.acceptFailed', 'Failed to accept invitation'));
    }
  }, [token, isAuthenticated, t]);

  /**
   * Handle invitation decline - redirect to home
   */
  const handleDecline = useCallback(() => {
    navigate('/', { replace: true });
  }, [navigate]);

  /**
   * Redirect to login with return URL
   */
  const redirectToLogin = useCallback(() => {
    navigate('/login', {
      replace: true,
      state: { from: currentPath },
    });
  }, [navigate, currentPath]);

  /**
   * Navigate to workspace after acceptance
   */
  // eslint-disable-next-line react-hooks/preserve-manual-memoization
  const navigateToWorkspace = useCallback(() => {
    if (invitationDetails?.tenantId) {
      navigate(`/tenant/${invitationDetails.tenantId}`, { replace: true });
    } else {
      navigate('/tenant', { replace: true });
    }
  }, [navigate, invitationDetails?.tenantId]);

  /**
   * Format role for display
   */
  const formatRole = (role: string): string => {
    const roleMap: Record<string, string> = {
      admin: t('inviteAccept.roles.admin', 'Admin'),
      member: t('inviteAccept.roles.member', 'Member'),
      viewer: t('inviteAccept.roles.viewer', 'Viewer'),
    };
    return roleMap[role] ?? role;
  };

  /**
   * Format expiration date
   */
  const formatExpiresAt = (expiresAt: string): string => {
    const date = new Date(expiresAt);
    return date.toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  // Loading state
  if (pageState === 'loading') {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50 dark:bg-gray-900">
        <Card className="w-full max-w-md mx-4">
          <Skeleton active paragraph={{ rows: 4 }} />
        </Card>
      </div>
    );
  }

  // Invalid or expired invitation
  if (pageState === 'invalid' || pageState === 'expired') {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50 dark:bg-gray-900">
        <Card className="w-full max-w-md mx-4">
          <Result
            status="error"
            title={t(
              pageState === 'expired' ? 'inviteAccept.expired.title' : 'inviteAccept.invalid.title',
              pageState === 'expired' ? 'Invitation Expired' : 'Invalid Invitation'
            )}
            subTitle={
              pageState === 'expired'
                ? t(
                    'inviteAccept.expired.description',
                    'This invitation has expired. Please contact the workspace admin for a new invitation.'
                  )
                : (errorMessage ??
                  t(
                    'inviteAccept.invalid.description',
                    'This invitation link is invalid or has already been used.'
                  ))
            }
            extra={[
              <Button key="home" type="primary" onClick={() => navigate('/', { replace: true })}>
                {t('inviteAccept.actions.goHome', 'Go to Home')}
              </Button>,
            ]}
          />
        </Card>
      </div>
    );
  }

  // Error state
  if (pageState === 'error') {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50 dark:bg-gray-900">
        <Card className="w-full max-w-md mx-4">
          <Result
            status="error"
            title={t('inviteAccept.error.title', 'Error')}
            subTitle={
              errorMessage ??
              t(
                'inviteAccept.error.description',
                'An error occurred while processing your invitation.'
              )
            }
            extra={[
              <Button
                key="retry"
                onClick={() => {
                  window.location.reload();
                }}
              >
                {t('common.actions.retry', 'Retry')}
              </Button>,
              <Button key="home" type="primary" onClick={() => navigate('/', { replace: true })}>
                {t('inviteAccept.actions.goHome', 'Go to Home')}
              </Button>,
            ]}
          />
        </Card>
      </div>
    );
  }

  // Accepted state
  if (pageState === 'accepted') {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50 dark:bg-gray-900">
        <Card className="w-full max-w-md mx-4">
          <Result
            status="success"
            title={t('inviteAccept.accepted.title', 'Welcome!')}
            subTitle={t(
              'inviteAccept.accepted.description',
              'You have successfully joined the workspace.'
            )}
            extra={[
              <Button key="workspace" type="primary" onClick={navigateToWorkspace}>
                {t('inviteAccept.actions.goToWorkspace', 'Go to Workspace')}
              </Button>,
            ]}
          />
        </Card>
      </div>
    );
  }

  // Not authenticated - show login prompt
  if (!isAuthenticated) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50 dark:bg-gray-900">
        <Card className="w-full max-w-md mx-4">
          <div className="text-center mb-6">
            <Mail size={48} className="text-blue-500 mb-4" />
            <Title level={3}>{t('inviteAccept.login.title', 'Accept Your Invitation')}</Title>
          </div>

          {invitationDetails && (
            <div className="mb-6 p-4 bg-gray-50 dark:bg-gray-800 rounded-lg">
              <Paragraph className="mb-2">
                <Text strong>{t('inviteAccept.fields.invitedEmail', 'Invited email')}:</Text>
                <br />
                <Text>{invitationDetails.email}</Text>
              </Paragraph>
              <Paragraph className="mb-2">
                <Text strong>{t('inviteAccept.fields.role', 'Role')}:</Text>
                <br />
                <Text>{formatRole(invitationDetails.role)}</Text>
              </Paragraph>
              {invitationDetails.expiresAt && (
                <Paragraph className="mb-0">
                  <Text strong>{t('inviteAccept.fields.expiresAt', 'Expires')}:</Text>
                  <br />
                  <Text>{formatExpiresAt(invitationDetails.expiresAt)}</Text>
                </Paragraph>
              )}
            </div>
          )}

          <Alert
            message={t('inviteAccept.login.prompt', 'Please log in to accept this invitation')}
            type="info"
            showIcon
            className="mb-4"
          />

          <Space direction="vertical" className="w-full">
            <Button type="primary" size="large" block onClick={redirectToLogin}>
              {t('common.login', 'Login')}
            </Button>
            <Button size="large" block onClick={handleDecline}>
              {t('inviteAccept.actions.decline', 'Decline')}
            </Button>
          </Space>
        </Card>
      </div>
    );
  }

  // Authenticated - show accept/decline
  const emailMismatch =
    user?.email && invitationDetails?.email && user.email !== invitationDetails.email;

  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-50 dark:bg-gray-900">
      <Card className="w-full max-w-md mx-4">
        <div className="text-center mb-6">
          <Mail className="text-5xl text-blue-500 mb-4" size={48} />
          <Title level={3}>{t('inviteAccept.authenticated.title', 'Workspace Invitation')}</Title>
        </div>

        {invitationDetails && (
          <div className="mb-6 p-4 bg-gray-50 dark:bg-gray-800 rounded-lg">
            <Paragraph className="mb-2">
              <Text strong>{t('inviteAccept.fields.invitedEmail', 'Invited email')}:</Text>
              <br />
              <Text>{invitationDetails.email}</Text>
            </Paragraph>
            <Paragraph className="mb-2">
              <Text strong>{t('inviteAccept.fields.workspaceId', 'Workspace ID')}:</Text>
              <br />
              <Text copyable={{ text: invitationDetails.tenantId }}>
                {invitationDetails.tenantId.slice(0, 8)}...
              </Text>
            </Paragraph>
            <Paragraph className="mb-2">
              <Text strong>{t('inviteAccept.fields.role', 'Role')}:</Text>
              <br />
              <Text>{formatRole(invitationDetails.role)}</Text>
            </Paragraph>
            {invitationDetails.expiresAt && (
              <Paragraph className="mb-0">
                <Text strong>{t('inviteAccept.fields.expiresAt', 'Expires')}:</Text>
                <br />
                <Text>{formatExpiresAt(invitationDetails.expiresAt)}</Text>
              </Paragraph>
            )}
          </div>
        )}

        {emailMismatch && (
          <Alert
            message={t('inviteAccept.emailMismatch.title', 'Email Mismatch')}
            description={t(
              'inviteAccept.emailMismatch.description',
              'This invitation was sent to {{invitedEmail}}, but you are logged in as {{currentEmail}}. You can still accept the invitation.',
              {
                invitedEmail: invitationDetails?.email,
                currentEmail: user?.email,
              }
            )}
            type="warning"
            showIcon
            className="mb-4"
          />
        )}

        {pageState === 'accepting' ? (
          <div className="text-center py-4">
            <Text>{t('inviteAccept.accepting', 'Accepting invitation...')}</Text>
          </div>
        ) : (
          <Space direction="vertical" className="w-full">
            <Button
              type="primary"
              size="large"
              block
              icon={<CheckCircle2 size={16} />}
              onClick={handleAccept}
            >
              {t('inviteAccept.actions.accept', 'Accept Invitation')}
            </Button>
            <Button
              size="large"
              block
              danger
              icon={<XCircle size={16} />}
              onClick={handleDecline}
            >
              {t('inviteAccept.actions.decline', 'Decline')}
            </Button>
          </Space>
        )}
      </Card>
    </div>
  );
};

export default InviteAccept;
