/**
 * ProjectManager.Search Component
 *
 * Search input component for filtering projects.
 */

import React, { FC, useState, useCallback } from 'react';

import { Search as SearchIcon } from 'lucide-react';

import { useProjectManagerContext } from './context';

import type { ProjectManagerSearchProps } from './types';

export const Search: FC<ProjectManagerSearchProps> = ({
  value: controlledValue,
  defaultValue = '',
  onChange,
  placeholder = '搜索项目...',
  className = '',
}) => {
  const context = useProjectManagerContext();
  const isControlled = controlledValue !== undefined;

  // Internal state for uncontrolled mode
  const [internalValue, setInternalValue] = useState(defaultValue);

  // Use controlled value or internal state
  const searchValue = isControlled ? controlledValue : internalValue;

  // Handle search input changes
  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const newValue = e.target.value;

      if (isControlled) {
        // Controlled mode - call onChange prop
        onChange?.(newValue);
      } else {
        // Uncontrolled mode - update internal state and context
        setInternalValue(newValue);
        context.setSearchTerm(newValue);
      }
    },
    [isControlled, onChange, context]
  );

  return (
    <div className={`flex-1 relative ${className}`}>
      <SearchIcon className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400 dark:text-slate-500" />
      <input
        type="text"
        data-testid="search-input"
        value={searchValue}
        onChange={handleChange}
        placeholder={placeholder}
        className="w-full pl-10 pr-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
        aria-label={placeholder}
      />
    </div>
  );
};
