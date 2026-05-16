import type React from 'react';

import { useTranslation } from 'react-i18next';

import { Alert, Input } from 'antd';

import { parseRawConfigJson } from '@/types/geneConfig';

export interface GeneConfigJsonEditorProps {
  value: string;
  onChange: (next: string) => void;
}

export const GeneConfigJsonEditor: React.FC<GeneConfigJsonEditorProps> = ({ value, onChange }) => {
  const { t } = useTranslation();
  const parsed = parseRawConfigJson(value);
  return (
    <div className="space-y-2">
      <Input.TextArea
        value={value}
        autoSize={{ minRows: 10, maxRows: 24 }}
        onChange={(e) => {
          onChange(e.target.value);
        }}
        style={{
          fontFamily: 'ui-monospace, Menlo, Monaco, "Courier New", monospace',
          fontSize: 12,
        }}
        spellCheck={false}
      />
      {!parsed.ok && (
        <Alert
          type="error"
          showIcon
          title={t('workspaceDetail.genes.config.invalidJson', 'Invalid JSON')}
          description={parsed.error}
        />
      )}
    </div>
  );
};
