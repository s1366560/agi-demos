import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { createInstance } from 'i18next';
import { I18nextProvider, useTranslation } from 'react-i18next';
import { ProjectSandboxSettings } from '../web/project/ProjectSandboxSettings';
import { secondaryButtonClass } from '../../../../../sdk/memstack-plugin-sdk/ui/SettingsSection';
import en from '../web/locales/en-US.json';
import zh from '../web/locales/zh-CN.json';
import './project-sandbox.css';

type Sandbox = { sandbox_id: string; status: string; last_accessed_at?: string };
const host = window.memstack;
function projectClient() {
  let sandboxId: string | undefined;
  return {
    async getProjectSandbox() {
      const { sandbox } = (await host.invoke('sandbox-status')) as { sandbox: Sandbox | null };
      sandboxId = sandbox?.sandbox_id;
      return sandbox;
    },
    async getStats() {
      const { metrics } = (await host.invoke('sandbox-status', { metrics_for: sandboxId })) as {
        metrics: { cpu_percent: number; memory_usage: number; memory_limit: number };
      };
      return {
        cpu_percent: metrics.cpu_percent,
        memory_used_mb: metrics.memory_usage / 1048576,
        memory_limit_mb: metrics.memory_limit / 1048576,
      };
    },
    restartSandbox: () => host.invoke('restart-sandbox'),
    terminateSandbox: () => host.invoke('terminate-sandbox'),
  };
}

function SandboxActions({ refresh, pathname }: { refresh: () => Promise<void>; pathname: string }) {
  const { t } = useTranslation();
  const [profile, setProfile] = useState('standard');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const prepare = async () => {
    setBusy(true);
    setError('');
    try {
      await host.invoke('prepare-sandbox', { profile });
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="mt-4 flex flex-wrap items-center gap-2">
      <select
        className={secondaryButtonClass}
        aria-label={t('project.settings.sandboxProfile')}
        value={profile}
        onChange={(event) => setProfile(event.target.value)}
      >
        {['lite', 'standard', 'full'].map((value) => (
          <option key={value}>{value}</option>
        ))}
      </select>
      <button
        type="button"
        className={secondaryButtonClass}
        disabled={busy}
        onClick={() => void prepare()}
      >
        {t('project.settings.sandboxPrepare')}
      </button>
      <button
        type="button"
        className={secondaryButtonClass}
        onClick={() => void host.navigate(pathname + '/runtime')}
      >
        {t('project.settings.sandboxRuntimeAccess')}
      </button>
      <button type="button" className={secondaryButtonClass} onClick={() => void host.navigate(pathname + '/connect')}>
        {t('project.settings.sandboxConnect')}
      </button>
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
async function mount() {
  const { projectId, locale, pathname } = await host.getContext();
  if (!projectId) throw new Error('project_scope_required');
  const i18n = createInstance();
  await i18n.init({
    lng: locale.startsWith('zh') ? 'zh' : 'en',
    resources: { en: { translation: en }, zh: { translation: zh } },
    interpolation: { escapeValue: false },
  });
  createRoot(document.getElementById('root')!).render(
    <I18nextProvider i18n={i18n}>
      <ProjectSandboxSettings
        projectId={projectId}
        client={projectClient()}
        actions={(refresh) => <SandboxActions refresh={refresh} pathname={pathname} />}
      />
    </I18nextProvider>
  );
}
void mount();
