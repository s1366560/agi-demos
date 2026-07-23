import React, { useEffect, useState } from 'react';

const numberInputClass =
  'w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2 text-slate-900 dark:text-white focus:border-primary focus:ring-1 focus:ring-primary outline-none';

/**
 * Number input that keeps a local string while editing so clearing the field
 * does not snap back to the default; commits parsed values and restores the
 * last valid value on blur.
 */
export const NumberInput: React.FC<{
  id: string;
  name: string;
  min?: number | undefined;
  max?: number | undefined;
  value: number;
  onCommit: (value: number) => void;
}> = ({ id, name, min, max, value, onCommit }) => {
  const [raw, setRaw] = useState(String(value));

  useEffect(() => {
    setRaw(String(value));
  }, [value]);

  return (
    <input
      id={id}
      name={name}
      type="number"
      min={min}
      max={max}
      value={raw}
      onChange={(e) => {
        setRaw(e.target.value);
        const parsed = parseInt(e.target.value, 10);
        if (!Number.isNaN(parsed)) {
          onCommit(parsed);
        }
      }}
      onBlur={() => {
        setRaw(String(value));
      }}
      className={numberInputClass}
    />
  );
};
