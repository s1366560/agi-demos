/**
 * ProjectManager.Filters Component
 *
 * Filter dropdown for filtering projects by status.
 */

import React, { FC, useState, useCallback, useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import { useProjectManagerContext } from './context';

import type { ProjectManagerFiltersProps } from './types';

export const Filters: FC<ProjectManagerFiltersProps> = ({
  value: controlledValue,
  defaultValue = 'all',
  onChange,
  options,
  className = '',
}) => {
  const { t } = useTranslation();
  const effectiveOptions = useMemo(
    () => options ?? [{ value: 'all', label: t('tenant.projectManager.filterAll') }],
    [options, t]
  );
  const context = useProjectManagerContext();
  const isControlled = controlledValue !== undefined;

  // Internal state for uncontrolled mode
  const [internalValue, setInternalValue] = useState(defaultValue);

  // Use controlled value or internal state
  const filterValue = isControlled ? controlledValue : internalValue;

  // Handle filter changes
  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      const newValue = e.target.value;

      if (isControlled) {
        // Controlled mode - call onChange prop
        onChange?.(newValue);
      } else {
        // Uncontrolled mode - update internal state and context
        setInternalValue(newValue);
        context.setFilterStatus(newValue);
      }
    },
    [isControlled, onChange, context]
  );

  return (
    <div className={`relative ${className}`}>
      <select
        data-testid="filter-select"
        value={filterValue}
        onChange={handleChange}
        className="px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
      >
        {effectiveOptions.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
};
