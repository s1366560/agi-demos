import '@radix-ui/themes/styles.css';
import { Theme } from '@radix-ui/themes';
import { createRoot } from 'react-dom/client';
import { I18nProvider } from '../i18n';
import { ThemePreferenceProvider, useThemePreference } from '../theme';
import { NativeSession } from './NativeSession';
import '../styles/tokens.css';
import '../styles/chrome.css';
import '../styles/base.css';
import '../app-shell.css';

function Application() {
  const { resolved } = useThemePreference();
  return (
    <Theme appearance={resolved} accentColor="gray" grayColor="slate" radius="medium" scaling="95%">
      <NativeSession />
    </Theme>
  );
}
document.documentElement.dataset.runtimeShell = 'electron';
document.documentElement.setAttribute('data-desktop-window', '');
createRoot(document.getElementById('root')!).render(
  <I18nProvider>
    <ThemePreferenceProvider>
      <Application />
    </ThemePreferenceProvider>
  </I18nProvider>,
);
