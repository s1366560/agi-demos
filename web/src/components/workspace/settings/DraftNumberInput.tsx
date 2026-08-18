import type React from 'react';
import { useState } from 'react';

import { Input } from 'antd';

export interface DraftNumberInputProps {
  id: string;
  min: number;
  value: number;
  fallback: number;
  onCommit: (value: number) => void;
}

/**
 * Number input that keeps raw text while editing and only commits the
 * fallback when the field is left empty on blur, so users can clear and
 * retype without the value snapping back to the default mid-edit.
 */
export const DraftNumberInput: React.FC<DraftNumberInputProps> = ({
  id,
  min,
  value,
  fallback,
  onCommit,
}) => {
  const [text, setText] = useState(String(value));
  const [lastValue, setLastValue] = useState(value);
  if (value !== lastValue) {
    // Sync when the draft value changes externally (reset / workspace reload).
    setLastValue(value);
    setText(String(value));
  }

  return (
    <Input
      id={id}
      type="number"
      min={min}
      value={text}
      onChange={(event) => {
        const raw = event.target.value;
        setText(raw);
        const parsed = Number(raw);
        if (raw.trim() !== '' && Number.isFinite(parsed)) {
          onCommit(parsed);
        }
      }}
      onBlur={() => {
        const parsed = Number(text);
        if (text.trim() === '' || !Number.isFinite(parsed)) {
          setText(String(fallback));
          onCommit(fallback);
        }
      }}
    />
  );
};
