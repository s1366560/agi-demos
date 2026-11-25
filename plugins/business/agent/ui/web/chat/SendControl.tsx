import { Button as LazyButton } from 'antd';
import { Square, Send } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export function SendControl({
  isStreaming,
  canSend,
  handleSend,
  onAbort,
}: {
  isStreaming: boolean;
  canSend: boolean;
  handleSend(): void;
  onAbort(): void;
}) {
  const { t } = useTranslation();
  return isStreaming ? (
    <LazyButton
      type="primary"
      danger
      size="small"
      icon={<Square size={14} className="fill-current" />}
      onClick={() => {
        onAbort();
      }}
      className="flex h-8 items-center gap-1.5 rounded-lg px-3 shadow-sm"
    >
      {t('agent.inputBar.stop', 'Stop')}
    </LazyButton>
  ) : (
    <LazyButton
      type="primary"
      size="small"
      icon={<Send size={14} />}
      onClick={handleSend}
      disabled={!canSend}
      aria-label={t('agent.inputBar.send', 'Send message')}
      data-testid="send-button"
      className={`
                rounded-lg flex items-center gap-1.5 h-8 px-2 xl:px-3
                bg-primary hover:bg-primary-600
                shadow-sm
                disabled:opacity-40 disabled:shadow-none disabled:cursor-not-allowed
                transition-colors duration-200
              `}
    >
      <span className="hidden xl:inline">{t('agent.inputBar.send', 'Send')}</span>
    </LazyButton>
  );
}
