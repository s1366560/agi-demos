import '@radix-ui/themes/styles.css';
import React, { useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Theme } from '@radix-ui/themes';

import {
  LoginScreen,
  type WorkspaceSsoPresentation,
} from '../features/auth/LoginScreen';
import { I18nProvider } from '../i18n';
import type { AuthState } from '../types';
import '../styles.css';

declare global {
  var __loginSsoQaRoot: Root | undefined;
}

const qaAuth: AuthState = {
  status: 'signed_out',
  credentialKind: null,
  session: null,
  context: null,
  user: null,
  tenants: [],
  projects: [],
  mustChangePassword: false,
  error: null,
};

const deviceAuthorization = {
  userCode: 'N7QK4X2P',
  authorizationUrl: 'https://app.memstack.ai/device?user_code=N7QK4X2P',
} satisfies Pick<WorkspaceSsoPresentation, 'userCode' | 'authorizationUrl'>;

const initialDeviceState = new URLSearchParams(window.location.search).get('state');

try {
  window.localStorage.setItem('agistack.desktop.locale', 'zh-CN');
} catch {
  // The QA surface still follows the browser locale if storage is unavailable.
}

function LoginSsoQa() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [deviceDialogOpen, setDeviceDialogOpen] = useState(true);
  const [expiresAt, setExpiresAt] = useState(() =>
    initialDeviceState === 'expired' ? Date.now() - 1000 : Date.now() + 10 * 60 * 1000,
  );
  const workspaceSso: WorkspaceSsoPresentation | null = deviceDialogOpen
    ? { ...deviceAuthorization, expiresAt, openError: null }
    : null;

  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <LoginScreen
        auth={qaAuth}
        mode="cloud"
        localReady={false}
        email={email}
        password={password}
        onEmailChange={setEmail}
        onPasswordChange={setPassword}
        onEmailLogin={() => undefined}
        onLocalSession={() => undefined}
        onWorkspaceSso={() => {
          setExpiresAt(Date.now() + 10 * 60 * 1000);
          setDeviceDialogOpen(true);
        }}
        workspaceSso={workspaceSso}
        onOpenWorkspaceSso={() => undefined}
        onCancelWorkspaceSso={() => setDeviceDialogOpen(false)}
      />
    </Theme>
  );
}

const container = document.getElementById('root');
if (!container) throw new Error('Missing root element');
globalThis.__loginSsoQaRoot ??= createRoot(container);
globalThis.__loginSsoQaRoot.render(
  <I18nProvider>
    <LoginSsoQa />
  </I18nProvider>,
);
