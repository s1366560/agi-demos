import { useTranslation } from 'react-i18next';
export function EmptyConversation({
  title,
  subtitle,
}: {
  title?: string | undefined;
  subtitle?: string | undefined;
}) {
  const { t } = useTranslation();
  return (
    <div className="h-full flex items-center justify-center">
      <div className="text-center text-slate-400">
        <p>
          {title || t('components.messageArea.emptyTitle', { defaultValue: 'No messages yet' })}
        </p>
        <p className="text-sm">
          {subtitle ||
            t('components.messageArea.emptySubtitle', {
              defaultValue: 'Start a conversation to see messages here',
            })}
        </p>
      </div>
    </div>
  );
}
