/**
 * AppHeader.Search - Compound Component
 *
 * Search input with icon and keyboard submit support.
 */

import * as React from 'react';

import { Search as SearchIcon } from 'lucide-react';

export interface SearchProps {
  autoFocus?: boolean | undefined;
  className?: string | undefined;
  id?: string | undefined;
  inputClassName?: string | undefined;
  value?: string | undefined;
  onChange?: ((value: string) => void) | undefined;
  onSubmit?: ((value: string) => void) | undefined;
  placeholder?: string | undefined;
  ariaLabel?: string | undefined;
}

export const Search = React.memo(function Search({
  autoFocus = false,
  className,
  id,
  inputClassName,
  value,
  onChange,
  onSubmit,
  placeholder = 'Search...',
  ariaLabel,
}: SearchProps) {
  const [uncontrolledValue, setUncontrolledValue] = React.useState('');
  const isControlled = value !== undefined;
  const currentValue = isControlled ? value : uncontrolledValue;

  const handleChange = (nextValue: string) => {
    if (!isControlled) {
      setUncontrolledValue(nextValue);
    }
    onChange?.(nextValue);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && onSubmit) {
      onSubmit(currentValue);
    }
  };

  return (
    <div className={className ?? 'relative hidden md:block group'}>
      <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 group-focus-within:text-primary w-4 h-4 transition-colors" />
      <input
        id={id}
        type="text"
        value={currentValue}
        onChange={(e) => {
          handleChange(e.target.value);
        }}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        aria-label={ariaLabel || placeholder}
        autoFocus={autoFocus}
        className={`input-search w-48 lg:w-64 transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-200 ${inputClassName ?? ''}`.trim()}
      />
    </div>
  );
});

Search.displayName = 'AppHeader.Search';
