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
