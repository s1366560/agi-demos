/**
 * IdleState - Agent workspace idle state
 *
 * Displays greeting and suggested starter tiles when no conversation is active.
 * Matches design from docs/statics/project workbench/agent/start/
 */

import { MaterialIcon } from '../shared';

export interface StarterTile {
  id: string;
  title: string;
  description: string;
  color: 'blue' | 'slate' | 'emerald' | 'primary';
  icon: string;
}

export interface IdleStateProps {
  /** Greeting message (default: "How can I help you today?") */
  greeting?: string;
  /** Starter tiles to display */
  starterTiles?: StarterTile[];
  /** Callback when a starter tile is clicked */
  onTileClick?: (tile: StarterTile) => void;
  /** Optional subtitle */
  subtitle?: string;
}

const DEFAULT_STARTER_TILES: StarterTile[] = [
  {
    id: 'trends',
    title: 'Analyze project trends',
    description: 'Identify key patterns across multiple data streams',
    color: 'blue',
    icon: 'analytics',
  },
  {
    id: 'reports',
    title: 'Synthesize Q4 reports',
    description: 'Aggregate complex findings into an executive summary',
    color: 'slate',
    icon: 'summarize',
  },
  {
    id: 'audit',
    title: 'Audit memory logs',
    description: 'Review system activity and trace data genealogy',
    color: 'emerald',
    icon: 'verified_user',
  },
  {
    id: 'compare',
    title: 'Cross-project comparison',
    description: 'Compare performance metrics between active projects',
    color: 'primary',
    icon: 'compare_arrows',
  },
];

const TILE_COLORS = {
  blue: {
    bg: 'bg-blue-50 dark:bg-primary/10',
    text: 'text-primary',
    hoverText: 'group-hover:text-primary',
  },
  slate: {
    bg: 'bg-slate-50 dark:bg-slate-500/10',
    text: 'text-slate-600',
    hoverText: 'group-hover:text-primary',
  },
  emerald: {
    bg: 'bg-emerald-50 dark:bg-emerald-500/10',
    text: 'text-emerald-600',
    hoverText: 'group-hover:text-primary',
  },
  primary: {
    bg: 'bg-blue-50 dark:bg-primary/10',
    text: 'text-primary',
    hoverText: 'group-hover:text-primary',
  },
};

/**
 * IdleState component
 *
 * @example
 * <IdleState
 *   greeting="How can I help you today?"
 *   onTileClick={(tile) => sendMessage(tile.title)}
 * />
 */
export function IdleState({
  greeting = 'How can I help you today?',
  starterTiles = DEFAULT_STARTER_TILES,
  onTileClick,
  subtitle,
}: IdleStateProps) {
  const handleTileClick = (tile: StarterTile) => {
    onTileClick?.(tile);
  };

  return (
    <>
      {/* Headline Section */}
      <div className="space-y-4">
        <h1 className="text-4xl md:text-5xl font-bold tracking-tight text-slate-900 dark:text-white">
          {greeting}
        </h1>
        {subtitle && (
          <p className="text-lg text-slate-500 dark:text-text-muted max-w-xl mx-auto">{subtitle}</p>
        )}
      </div>

      {/* Suggested Starter Tiles */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 p-4">
        {starterTiles.map((tile) => {
          const colors = TILE_COLORS[tile.color];

          return (
            <button
              key={tile.id}
              onClick={() => handleTileClick(tile)}
              className={`group flex flex-col items-start p-5 bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-xl hover:border-primary hover:shadow-xl hover:-translate-y-1 transition-all duration-200 cursor-pointer text-left`}
            >
              <div className={`mb-4 p-2 rounded-lg ${colors.bg} ${colors.text}`}>
                <MaterialIcon name={tile.icon as any} size={24} />
              </div>
              <h3 className={`text-sm font-semibold mb-1 ${colors.hoverText} transition-colors`}>
                {tile.title}
              </h3>
              <p className="text-xs text-text-muted">{tile.description}</p>
            </button>
          );
        })}
      </div>
    </>
  );
}

export default IdleState;
