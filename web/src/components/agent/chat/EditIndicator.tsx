import { memo } from 'react';

import { useTranslation } from 'react-i18next';

import { Pencil } from 'lucide-react';

interface EditIndicatorProps {
  version: number;
  editedAt?: string;
}

export const EditIndicator = memo<EditIndicatorProps>(
  ({ version, editedAt: _editedAt }) => {
    const { t } = useTranslation();
    if (version <= 1) return null;

    return (
      <span className="inline-flex items-center gap-1 text-[10px] text-slate-400 ml-2">
        <Pencil size={10} />
        {t('agent.version.edited', 'edited')}
        {version > 2 && (
          <span className="text-slate-300">v{version}</span>
        )}
      </span>
    );
  }
);
EditIndicator.displayName = 'EditIndicator';
