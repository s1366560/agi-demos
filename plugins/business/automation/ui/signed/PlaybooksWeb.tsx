import { createInstance } from 'i18next';
import { createRoot } from 'react-dom/client';
import { I18nextProvider } from 'react-i18next';
import { PlaybookLibraryView } from '../web/project/PlaybookLibraryView';
import en from '../web/locales/en-US.json';
import zh from '../web/locales/zh-CN.json';
import { useReflectionLibrary } from './useReflectionLibrary';
import './playbooks-web.css';

function Playbooks() {
  return <PlaybookLibraryView {...useReflectionLibrary()} />;
}

async function mount() {
  const { locale } = await window.memstack.getContext();
  const i18n = createInstance();
  await i18n.init({
    lng: locale.startsWith('zh') ? 'zh' : 'en',
    resources: {
      en: { translation: en },
      zh: { translation: zh },
    },
    interpolation: { escapeValue: false },
  });
  createRoot(document.getElementById('root')!).render(
    <I18nextProvider i18n={i18n}>
      <Playbooks />
    </I18nextProvider>
  );
}
void mount();
