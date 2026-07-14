import { type MouseEvent, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Badge, Button, IconButton, Text, TextField } from '@radix-ui/themes';
import {
  ChatBubbleIcon,
  Cross2Icon,
  EnterIcon,
  ExitIcon,
  GearIcon,
  PersonIcon,
} from '@radix-ui/react-icons';

import { LOCAL_DEV_SERVER_PRESETS } from '../../types';
import type { AuthState, DesktopRuntimeConfig } from '../../types';

type AuthPanelProps = {
  auth: AuthState;
  config: DesktopRuntimeConfig;
  email: string;
  password: string;
  onApiBaseUrlChange: (value: string) => void;
  onEmailChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onLogin: () => void;
  onUseApiKeyManually: () => void;
  onLogout: () => void;
  onOpenSettings: () => void;
  loginOpen?: boolean;
  onLoginOpenChange?: (open: boolean) => void;
  getLoginRestoreTarget?: () => HTMLElement | null;
};

const LOCAL_DEV_ADMIN_EMAIL = import.meta.env.DEV ? 'admin@memstack.ai' : '';
const LOCAL_DEV_ADMIN_PASSWORD = import.meta.env.DEV ? 'adminpassword' : '';

export function AuthPanel({
  auth,
  config,
  email,
  password,
  onApiBaseUrlChange,
  onEmailChange,
  onPasswordChange,
  onLogin,
  onUseApiKeyManually,
  onLogout,
  onOpenSettings,
  loginOpen: controlledLoginOpen,
  onLoginOpenChange,
  getLoginRestoreTarget,
}: AuthPanelProps) {
  const selectedTenant = auth.tenants.find((tenant) => tenant.id === config.tenantId);
  const selectedProject = auth.projects.find((project) => project.id === config.projectId);
  const signingIn = auth.status === 'signing_in';
  const localDevBase = import.meta.env.DEV && isLocalDevBase(config.apiBaseUrl);
  const [internalLoginOpen, setInternalLoginOpen] = useState(false);
  const [feedbackStatus, setFeedbackStatus] = useState<string | null>(null);
  const loginOpen = controlledLoginOpen ?? internalLoginOpen;
  const setLoginOpen = onLoginOpenChange ?? setInternalLoginOpen;
  const emailInputRef = useRef<HTMLInputElement>(null);
  const loginModalRef = useRef<HTMLElement>(null);
  const loginTriggerRef = useRef<HTMLElement | null>(null);
  const wasLoginOpenRef = useRef(false);
  const feedbackStatusTimeoutRef = useRef<number | null>(null);
  const openLogin = (trigger?: HTMLElement | null) => {
    loginTriggerRef.current =
      trigger ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    setLoginOpen(true);
  };
  const profileAction = (event: MouseEvent<HTMLButtonElement>) => {
    if (auth.status === 'manual') {
      onOpenSettings();
      return;
    }
    openLogin(event.currentTarget);
  };
  const fillLocalDevAdmin = () => {
    onEmailChange(LOCAL_DEV_ADMIN_EMAIL);
    onPasswordChange(LOCAL_DEV_ADMIN_PASSWORD);
  };
  const applyLocalDevPreset = (apiBaseUrl: string) => {
    onApiBaseUrlChange(apiBaseUrl);
    fillLocalDevAdmin();
  };
  const accountLabel = auth.user?.name || auth.user?.email || 'Signed in';
  const accountScope = `${selectedTenant?.name ?? config.tenantId ?? '-'} / ${
    config.workspaceId || 'workspace -'
  }`;
  const copyFeedbackContext = async () => {
    const feedbackContext = [
      'agi-stack Desktop feedback',
      `Account: ${accountLabel}`,
      `Tenant: ${selectedTenant?.name ?? config.tenantId ?? '-'}`,
      `Project: ${selectedProject?.name ?? config.projectId ?? '-'}`,
      `Workspace: ${config.workspaceId || '-'}`,
      `Server: ${config.apiBaseUrl}`,
    ].join('\n');

    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(feedbackContext);
      } else {
        copyTextFallback(feedbackContext);
      }
      setFeedbackStatus('Feedback details copied');
    } catch {
      copyTextFallback(feedbackContext);
      setFeedbackStatus('Feedback details copied');
    }

    if (feedbackStatusTimeoutRef.current) {
      window.clearTimeout(feedbackStatusTimeoutRef.current);
    }
    feedbackStatusTimeoutRef.current = window.setTimeout(() => {
      setFeedbackStatus(null);
      feedbackStatusTimeoutRef.current = null;
    }, 2200);
  };

  useEffect(() => {
    const canPrimeLocalPreset =
      loginOpen && localDevBase && !password && (!email || email === LOCAL_DEV_ADMIN_EMAIL);
    if (!canPrimeLocalPreset) return;
    onEmailChange(LOCAL_DEV_ADMIN_EMAIL);
    onPasswordChange(LOCAL_DEV_ADMIN_PASSWORD);
  }, [email, localDevBase, loginOpen, onEmailChange, onPasswordChange, password]);

  const closeLogin = (restoreFocus = true) => {
    const trigger = loginTriggerRef.current;
    const fallback = getLoginRestoreTarget?.();
    const focusTarget = isRestoreTarget(trigger, loginModalRef.current)
      ? trigger
      : isRestoreTarget(fallback, loginModalRef.current)
        ? fallback
        : null;
    setLoginOpen(false);
    loginTriggerRef.current = null;
    if (restoreFocus && focusTarget) {
      window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => {
          if (focusTarget.isConnected) {
            focusTarget.focus();
          }
        });
      });
    }
  };

  useEffect(() => {
    if (auth.status === 'manual' || auth.status === 'signed_in') {
      setLoginOpen(false);
    }
  }, [auth.status]);

  useEffect(
    () => () => {
      if (feedbackStatusTimeoutRef.current) {
        window.clearTimeout(feedbackStatusTimeoutRef.current);
      }
    },
    [],
  );

  useEffect(() => {
    if (!loginOpen) return;

    if (!wasLoginOpenRef.current && !loginTriggerRef.current) {
      loginTriggerRef.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
    }
    wasLoginOpenRef.current = true;
    window.requestAnimationFrame(() => emailInputRef.current?.focus());

    const handleDialogKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeLogin();
        return;
      }
      if (event.key !== 'Tab') return;
      const focusableElements = getFocusableElements(loginModalRef.current);
      if (!focusableElements.length) return;
      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];
      if (event.shiftKey && document.activeElement === firstElement) {
        event.preventDefault();
        lastElement.focus();
        return;
      }
      if (!event.shiftKey && document.activeElement === lastElement) {
        event.preventDefault();
        firstElement.focus();
      }
    };

    const keepFocusInsideDialog = (event: FocusEvent) => {
      if (!loginModalRef.current) return;
      const target = event.target;
      if (target instanceof Node && loginModalRef.current.contains(target)) return;
      const focusableElements = getFocusableElements(loginModalRef.current);
      const nextFocus = focusableElements.includes(emailInputRef.current as HTMLElement)
        ? emailInputRef.current
        : focusableElements[0];
      if (!nextFocus) return;
      event.preventDefault();
      window.requestAnimationFrame(() => nextFocus.focus());
    };

    window.addEventListener('keydown', handleDialogKeyDown);
    window.addEventListener('focusin', keepFocusInsideDialog);
    return () => {
      window.removeEventListener('keydown', handleDialogKeyDown);
      window.removeEventListener('focusin', keepFocusInsideDialog);
    };
  }, [loginOpen]);

  useEffect(() => {
    if (loginOpen) return;
    wasLoginOpenRef.current = false;
    loginTriggerRef.current = null;
  }, [loginOpen]);

  const loginDialog = loginOpen ? (
    <div className="auth-modal-backdrop" onMouseDown={() => closeLogin()}>
      <section
        ref={loginModalRef}
        className="auth-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Sign in to agi-stack"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="auth-modal-header">
          <div>
            <Text as="div" size="5" weight="bold" mb="2">
              Sign in to agi-stack
            </Text>
            <Text as="p" size="2" color="gray">
              Your sign-in stays in this window for the current session.
            </Text>
          </div>
          <IconButton
            size="1"
            variant="ghost"
            color="gray"
            className="auth-close-button"
            aria-label="Close sign in dialog"
            onClick={() => closeLogin()}
          >
            <Cross2Icon />
          </IconButton>
        </div>

        <form
          className="auth-form"
          onSubmit={(event) => {
            event.preventDefault();
            onLogin();
          }}
        >
          <label className="field-label">
            <span>Server URL</span>
            <TextField.Root
              aria-label="Login server URL"
              name="api_base_url"
              type="url"
              value={config.apiBaseUrl}
              disabled={signingIn}
              onChange={(event) => onApiBaseUrlChange(event.target.value)}
              placeholder="http://127.0.0.1:8000"
            />
          </label>
          <label className="field-label">
            <span>Email</span>
            <TextField.Root
              ref={emailInputRef}
              aria-label="Email"
              autoComplete="username"
              name="username"
              type="email"
              value={email}
              disabled={signingIn}
              onChange={(event) => onEmailChange(event.target.value)}
              placeholder="admin@memstack.ai"
            />
          </label>
          <label className="field-label">
            <span>Password</span>
            <TextField.Root
              aria-label="Password"
              autoComplete="current-password"
              name="password"
              type="password"
              value={password}
              disabled={signingIn}
              onChange={(event) => onPasswordChange(event.target.value)}
              placeholder="Password"
            />
          </label>
          {localDevBase ? (
            <div className="auth-dev-helper">
              <Text size="1" color="gray" className="auth-hint">
                Local development presets fill the test admin account for this session. Choose
                the server that is actually running.
              </Text>
              <div className="auth-dev-presets" aria-label="Local development server presets">
                {LOCAL_DEV_SERVER_PRESETS.map((preset) => (
                  <Button
                    key={preset.id}
                    size="1"
                    type="button"
                    variant="surface"
                    color="gray"
                    className="auth-fill-dev-button"
                    disabled={signingIn}
                    aria-pressed={config.apiBaseUrl === preset.apiBaseUrl}
                    onClick={() => applyLocalDevPreset(preset.apiBaseUrl)}
                  >
                    Use {preset.label}
                  </Button>
                ))}
              </div>
            </div>
          ) : null}
          {auth.error ? (
            <Text size="1" color="red" className="auth-error" role="alert" aria-live="polite">
              {auth.error}
            </Text>
          ) : null}
          <div className="auth-modal-actions">
            <Button
              size="2"
              type="button"
              variant="surface"
              color="gray"
              className="auth-cancel-button"
              onClick={() => closeLogin()}
            >
              Cancel
            </Button>
            <Button
              size="2"
              type="submit"
              className="auth-login-button"
              loading={signingIn}
              disabled={!email || !password}
            >
              <EnterIcon /> Login
            </Button>
          </div>
        </form>
        <Button
          size="2"
          variant="surface"
          color="gray"
          className="auth-manual-fallback"
          aria-label="Use API key from sign in dialog"
          onClick={() => {
            closeLogin(false);
            onUseApiKeyManually();
          }}
        >
          Use API key manually
        </Button>
      </section>
    </div>
  ) : null;

  if (auth.status === 'signed_in') {
    return (
      <section className="auth-panel account-panel signed-in">
        <div className="account-row">
          <div className="account-avatar">
            <PersonIcon />
          </div>
          <div className="account-copy">
            <Text size="2" weight="bold">
              {accountLabel}
            </Text>
            <Text size="1" color="gray">
              {selectedProject?.name ?? (config.projectId || auth.user?.email)}
            </Text>
          </div>
          <div className="account-actions">
            {auth.mustChangePassword ? (
              <Badge color="amber" variant="soft">
                password
              </Badge>
            ) : null}
            <IconButton
              size="1"
              variant="ghost"
              color={feedbackStatus ? 'cyan' : 'gray'}
              aria-label="Share feedback"
              title="Share feedback"
              onClick={() => void copyFeedbackContext()}
            >
              <ChatBubbleIcon />
            </IconButton>
            <IconButton
              size="1"
              variant="ghost"
              color="gray"
              aria-label="Settings"
              onClick={onOpenSettings}
            >
              <GearIcon />
            </IconButton>
            <IconButton size="1" variant="ghost" color="gray" aria-label="Logout" onClick={onLogout}>
              <ExitIcon />
            </IconButton>
          </div>
        </div>
        <Text
          size="1"
          color={feedbackStatus ? 'cyan' : 'gray'}
          className="account-scope"
          aria-live="polite"
        >
          {feedbackStatus ?? accountScope}
        </Text>
      </section>
    );
  }

  return (
    <section className="auth-panel account-panel">
      <div className="account-row">
        <button
          className="account-profile-button"
          type="button"
          aria-label={auth.status === 'manual' ? 'Open connection settings' : 'Sign in to agi-stack'}
          onClick={profileAction}
        >
          <span className="account-avatar">
            <PersonIcon />
          </span>
          <span className="account-copy">
            <Text size="2" weight="bold">
              {auth.status === 'manual' ? 'Manual key' : 'Sign in'}
            </Text>
            <Text size="1" color="gray">
              {auth.status === 'manual' ? config.apiBaseUrl.replace(/^https?:\/\//, '') : 'agi-stack'}
            </Text>
          </span>
        </button>
        <div className="account-actions">
          {auth.status === 'manual' ? null : (
            <IconButton
              size="1"
              variant="ghost"
              color="gray"
              aria-label="Open sign in dialog from account panel"
              onClick={(event) => openLogin(event.currentTarget)}
            >
              <ChatBubbleIcon />
            </IconButton>
          )}
          <IconButton
            size="1"
            variant="ghost"
            color="gray"
            aria-label="Settings"
            onClick={onOpenSettings}
          >
            <GearIcon />
          </IconButton>
        </div>
      </div>

      {loginDialog ? createPortal(loginDialog, document.body) : null}
    </section>
  );
}

function isLocalDevBase(value: string): boolean {
  try {
    const host = new URL(value).hostname;
    return host === 'localhost' || host === '127.0.0.1' || host === '::1';
  } catch {
    return false;
  }
}

function isRestoreTarget(
  element: HTMLElement | null | undefined,
  modal: HTMLElement | null,
): element is HTMLElement {
  return Boolean(element?.isConnected && element !== document.body && !modal?.contains(element));
}

function getFocusableElements(container: HTMLElement | null): HTMLElement[] {
  if (!container) return [];
  const selectors = [
    'a[href]',
    'button:not(:disabled)',
    'input:not(:disabled)',
    'textarea:not(:disabled)',
    'select:not(:disabled)',
    '[tabindex]:not([tabindex="-1"])',
  ].join(',');
  return Array.from(container.querySelectorAll<HTMLElement>(selectors)).filter(
    (element) => !element.hasAttribute('disabled') && !element.getAttribute('aria-hidden'),
  );
}

function copyTextFallback(value: string) {
  const textArea = document.createElement('textarea');
  textArea.value = value;
  textArea.setAttribute('readonly', '');
  textArea.style.position = 'fixed';
  textArea.style.top = '-9999px';
  document.body.appendChild(textArea);
  textArea.select();
  document.execCommand('copy');
  textArea.remove();
}
