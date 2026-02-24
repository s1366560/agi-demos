/**
 * EntityCard Component
 *
 * Displays a single entity in a card format with:
 * - Entity name and type badge
 * - Entity summary (with line clamp)
 * - Created date
 * - Click handler
 * - Selected state styling
 *
 * Extracted from EntitiesList page for reusability and virtual scrolling support.
 */

import React, { memo } from 'react';

import { useTranslation } from 'react-i18next';

import { formatDateOnly } from '@/utils/date';

export interface Entity {
  uuid: string;
  name: string;
  entity_type: string;
  summary: string;
  created_at?: string;
}

export interface EntityCardProps {
  /** The entity to display */
  entity: Entity;
  /** Click handler for the card */
  onClick: (entity: Entity) => void;
  /** Whether this entity is currently selected */
  isSelected?: boolean;
}

// Predefined colors for common entity types (matching EntitiesList)
const predefinedColors: Record<string, string> = {
  Person: 'bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-400',
  Organization: 'bg-cyan-100 text-cyan-800 dark:bg-cyan-900/30 dark:text-cyan-400',
  Product: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400',
  Location: 'bg-lime-100 text-lime-800 dark:bg-lime-900/30 dark:text-lime-400',
  Event: 'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-400',
  Concept: 'bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-400',
  Technology: 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900/30 dark:text-indigo-400',
  Entity: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400',
};

// Color palette for custom entity types
const customColorPalette = [
  'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-400',
  'bg-teal-100 text-teal-800 dark:bg-teal-900/30 dark:text-teal-400',
  'bg-sky-100 text-sky-800 dark:bg-sky-900/30 dark:text-sky-400',
  'bg-violet-100 text-violet-800 dark:bg-violet-900/30 dark:text-violet-400',
  'bg-fuchsia-100 text-fuchsia-800 dark:bg-fuchsia-900/30 dark:text-fuchsia-400',
  'bg-pink-100 text-pink-800 dark:bg-pink-900/30 dark:text-pink-400',
  'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400',
  'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400',
];

/**
 * Generate consistent color for entity type (including custom schemas)
 * Exported for reuse in other components
 */
 
// eslint-disable-next-line react-refresh/only-export-components
export const getEntityTypeColor = (entityType: string): string => {
  if (predefinedColors[entityType]) {
    return predefinedColors[entityType];
  }
  // Generate a consistent color based on entity type name hash
  const hash = entityType.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
  return customColorPalette[hash % customColorPalette.length] ?? '#6b7280';
};

/**
 * Internal EntityCard component implementation
 */
const EntityCardInternal: React.FC<EntityCardProps> = ({ entity, onClick, isSelected = false }) => {
  const { t } = useTranslation();

  const handleClick = () => {
    onClick(entity);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      onClick(entity);
    }
  };

  const entityTypeColor = getEntityTypeColor(entity.entity_type || 'Unknown');

  return (
    <div
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      role="button"
      tabIndex={0}
      className={`bg-white dark:bg-slate-800 rounded-lg border p-4 cursor-pointer transition-all hover:shadow-md ${
        isSelected
          ? 'border-blue-500 shadow-md ring-2 ring-blue-500 ring-opacity-20'
          : 'border-slate-200 dark:border-slate-700'
      }`}
    >
      <div className="flex items-start justify-between mb-2">
        <h3 className="font-semibold text-slate-900 dark:text-white flex-1">{entity.name}</h3>
        <span className={`px-2 py-1 rounded-full text-xs font-medium ml-2 ${entityTypeColor}`}>
          {entity.entity_type || t('common.status.unknown', 'Unknown')}
        </span>
      </div>
      {entity.summary && (
        <p className="text-sm text-slate-600 dark:text-slate-400 line-clamp-2">{entity.summary}</p>
      )}
      <div className="mt-2 text-xs text-slate-500">
        {t('project.graph.entities.detail.created')}:{' '}
        {entity.created_at
          ? formatDateOnly(entity.created_at)
          : t('common.status.unknown', 'Unknown')}
      </div>
    </div>
  );
};

/**
 * Memoized EntityCard component.
 * Prevents unnecessary re-renders when parent components update.
 */
export const EntityCard = memo(EntityCardInternal);
