import '@radix-ui/themes/styles.css';
import React, { useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { CheckCircledIcon } from '@radix-ui/react-icons';
import { Theme } from '@radix-ui/themes';

import { ForcePasswordChangeScreen } from '../features/auth/ForcePasswordChangeScreen';
import { I18nProvider } from '../i18n';
import '../styles/global.css';
import './forcePasswordChangeQa.css';

declare global {
  var __forcePasswordChangeQaRoot: Root | undefined;
}

type QaStage = 'required' | 'submitting' | 'success';

try {
  window.localStorage.setItem('agistack.desktop.locale', 'zh-CN');
} catch {
  // Browser locale remains the fallback when the QA preference cannot be stored.
}

function ForcePasswordChangeQa() {
  const [stage, setStage] = useState<QaStage>('required');
  const [error, setError] = useState<string | null>(null);

  if (stage === 'success') {
    return (
      <main className="force-password-qa-success" data-qa-status="workspace-ready">
        <CheckCircledIcon />
        <span>AUTHENTICATED WORKSPACE</span>
        <h1>密码已更新</h1>
        <p>受支持的云端会话已建立，临时登录凭据没有写入浏览器存储。</p>
        <button
          type="button"
          onClick={() => {
            setError(null);
            setStage('required');
          }}
        >
          重置强制改密门禁
        </button>
      </main>
    );
  }

  return (
    <div data-qa-status={stage}>
      <ForcePasswordChangeScreen
        busy={stage === 'submitting'}
        error={error}
        onSubmit={(currentPassword) => {
          setError(null);
          if (currentPassword !== 'adminpassword') {
            setError('当前密码不正确，请重试。');
            return;
          }
          setStage('submitting');
          window.setTimeout(() => setStage('success'), 350);
        }}
        onSignOut={() => {
          setError('临时会话已撤销；重新登录后仍会返回强制改密门禁。');
        }}
      />
    </div>
  );
}

const container = document.getElementById('root');
if (!container) throw new Error('Missing root element');
globalThis.__forcePasswordChangeQaRoot ??= createRoot(container);
globalThis.__forcePasswordChangeQaRoot.render(
  <I18nProvider>
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <ForcePasswordChangeQa />
    </Theme>
  </I18nProvider>,
);
