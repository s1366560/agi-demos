import { useI18n } from '../../i18n';
import type { SubagentToolActivity } from './subagentToolActivityModel';

export function SubagentToolActivityList({ items }: { items: readonly SubagentToolActivity[] }) {
  const { t } = useI18n();
  if (items.length === 0) return null;
  return (
    <section className="timeline-details">
      <strong>{t('chat.callsCount', { count: items.length })}</strong>
      {items.map((item) => (
        <details key={item.id} className="timeline-details" data-child-tool-status={item.status}>
          <summary>
            {item.toolName} · {t(`chat.subagentStatus.${item.status}`)}
          </summary>
          {item.input !== undefined ? (
            <>
              <strong>{t('chat.input')}</strong>
              <pre>{item.input}</pre>
            </>
          ) : null}
          {item.output !== undefined ? (
            <>
              <strong>{t('chat.output')}</strong>
              <pre>{item.output}</pre>
            </>
          ) : null}
          {item.error ? <p role="alert">{item.error}</p> : null}
        </details>
      ))}
    </section>
  );
}
