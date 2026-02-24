/**
 * AppHeader.Search - Compound Component
 *
 * Search input with icon and keyboard submit support.
 */

import * as React from 'react';

import { Search as SearchIcon } from 'lucide-react';

export interface SearchProps {
  value?: string | undefined;
  onChange?: ((value: string) => void) | undefined;
  onSubmit?: ((value: string) => void) | undefined;
  placeholder?: string | undefined;
  ariaLabel?: string | undefined;
}

export const Search = React.memo(function Search({
  value = '',
  onChange,
  onSubmit,
  placeholder = 'Search...',
  ariaLabel,
}: SearchProps) {
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && onSubmit) {
      onSubmit(value);
    }
  };

  return (
    <div className="relative hidden md:block group">
      <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 group-focus-within:text-primary w-4 h-4 transition-colors" />
      <input
        type="text"
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        aria-label={ariaLabel || placeholder}
        className="input-search w-48 lg:w-64 transition-all duration-200"
      />
    </div>
  );
});

Search.displayName = 'AppHeader.Search';
