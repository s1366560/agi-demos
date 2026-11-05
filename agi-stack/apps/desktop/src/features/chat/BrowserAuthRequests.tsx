import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Button, Flex, Text } from '@radix-ui/themes';
import { useI18n } from '../../i18n';
import type { DesktopRuntimeConfig } from '../../types';
async function invokeBrowserAuth(command: string, args: Record<string, unknown>): Promise<unknown> {
  const invoke = window.__MEMSTACK_DESKTOP__?.core?.invoke;
  if (!invoke) throw new Error('browser_auth_native_bridge_unavailable');
  return invoke(command, args);
}

type AuthField = Readonly<{ id: string; label: string; type: string; required: boolean }>;
type AuthOption = Readonly<{ id: string; label: string; field_ids: readonly string[] }>;
type AuthPrompt = Readonly<{
  request_id: string;
  origin: string;
  expires_at: string;
  account_identifier: string | null;
  qr_image?: string | null;
  fields: readonly AuthField[];
  options: readonly AuthOption[];
}>;

function prompts(value: unknown): AuthPrompt[] {
  if (!value || typeof value !== 'object' || !('requests' in value) || !Array.isArray(value.requests)) return [];
  return value.requests.filter((item): item is AuthPrompt => item && typeof item === 'object'
    && typeof item.request_id === 'string' && typeof item.origin === 'string'
    && typeof item.expires_at === 'string' && Date.parse(item.expires_at) > Date.now()
    && Array.isArray(item.fields) && Array.isArray(item.options)
    && item.fields.every((field: AuthField) => field && typeof field.id === 'string' && typeof field.label === 'string' && typeof field.required === 'boolean')
    && item.options.every((option: AuthOption) => option && typeof option.id === 'string' && typeof option.label === 'string' && Array.isArray(option.field_ids)));
}

export function BrowserAuthRequests({ config, conversationId }: Readonly<{
  config: DesktopRuntimeConfig | undefined;
  conversationId: string;
}>) {
  const { t } = useI18n();
  const [pollFailed, setPollFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  const [pending, setPending] = useState<AuthPrompt[]>([]);
  const latestConfig = useRef(config);
  latestConfig.current = config;
  useEffect(() => { setPending([]); setPollFailed(false); }, [conversationId, config?.mode, config?.apiKey, config?.localApiToken]);
  useEffect(() => {
    const activeConfig = latestConfig.current;
    if (!activeConfig || !conversationId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const result = await invokeBrowserAuth('browser_auth_pending', { conversation_id: conversationId });
        if (!controller.signal.aborted) { setPending(prompts(result)); setPollFailed(false); }
      } catch { if (!controller.signal.aborted) setPollFailed(true); }
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 1000);
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [config?.mode, config?.apiBaseUrl, config?.apiKey, config?.localApiToken, conversationId, retry]);
  if (!config || (pending.length === 0 && !pollFailed)) return null;
  return <>{pollFailed ? <div role="alert" className="timeline-details"><Text>{t('chat.browserAuth.pollFailed')}</Text><Button type="button" onClick={() => setRetry(current => current + 1)}>{t('common.retry')}</Button></div> : null}{pending.map(prompt => <BrowserAuthForm key={prompt.request_id} prompt={prompt} conversationId={conversationId}
    onCompleted={() => setPending(current => current.filter(item => item.request_id !== prompt.request_id))} />)}</>;
}

function BrowserAuthForm({ prompt, conversationId, onCompleted }: Readonly<{
  prompt: AuthPrompt;
  conversationId: string;
  onCompleted: () => void;
}>) {
  const { t } = useI18n();
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const selectedFields = prompt.options.length === 0 ? prompt.fields
    : prompt.fields.filter(field => prompt.options.find(option => option.id === selected)?.field_ids.includes(field.id));
  const respond = async (action: 'submit' | 'decline', event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    if (busy) return;
    const form = event?.currentTarget;
    const values: Record<string, string> = {};
    if (action === 'submit' && form) {
      const data = new FormData(form);
      for (const field of selectedFields) values[field.id] = String(data.get(field.id) ?? '');
    }
    form?.reset();
    setBusy(true);
    setFailed(false);
    try {
      await invokeBrowserAuth('browser_auth_respond', {
        request_id: prompt.request_id, conversation_id: conversationId,
        response: { action, ...(action === 'submit' && prompt.options.length ? { selected_option: selected } : {}), values },
      });
      onCompleted();
    } catch { setFailed(true); }
    finally { for (const key of Object.keys(values)) values[key] = ''; setBusy(false); }
  };
  return <section className="timeline-details hitl-response-card" aria-label={t('chat.browserAuth.title', { origin: prompt.origin })}>
    <form onSubmit={event => void respond('submit', event)} autoComplete="off">
      <Flex direction="column" gap="3">
        <Text as="p" weight="bold">{t('chat.browserAuth.title', { origin: prompt.origin })}</Text>
        <Text as="p" size="2">{t('chat.browserAuth.description')}</Text>
        {prompt.account_identifier ? <Text as="p" size="2">{prompt.account_identifier}</Text> : null}
        {prompt.qr_image?.startsWith('data:image/png;base64,') ? <>
          <Text as="p" size="2">{t('chat.browserAuth.qrDescription')}</Text>
          <img src={prompt.qr_image} alt={t('chat.browserAuth.qrImage')} style={{ maxWidth: '100%', maxHeight: 420, objectFit: 'contain' }} />
        </> : null}
        {prompt.options.length ? <label>
          <Text as="span" size="2">{t('chat.browserAuth.method')}</Text>
          <select value={selected} required disabled={busy} onChange={event => setSelected(event.target.value)}>
            <option value="">{t('chat.browserAuth.chooseMethod')}</option>
            {prompt.options.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
          </select>
        </label> : null}
        {selectedFields.map(field => <label key={`${selected}:${field.id}`}>
          <Text as="span" size="2">{field.label}</Text>
          <input name={field.id} type="password" required={field.required} disabled={busy}
            autoComplete="off" autoCorrect="off" spellCheck={false} maxLength={4096} />
        </label>)}
        {failed ? <Text as="p" color="red" role="alert">{t('chat.browserAuth.failed')}</Text> : null}
        <Flex gap="2">
          <Button type="submit" disabled={busy || (prompt.options.length > 0 && !selected)}>{t(busy ? 'chat.browserAuth.submitting' : prompt.qr_image ? 'chat.browserAuth.qrConfirm' : 'chat.browserAuth.continue')}</Button>
          <Button type="button" variant="soft" disabled={busy} onClick={() => void respond('decline')}>{t('chat.browserAuth.decline')}</Button>
        </Flex>
      </Flex>
    </form>
  </section>;
}
