/**
 * EmptyStateVariant - Flexible empty state component with variants
 *
 * Provides two variants:
 * - simple: Basic centered state with icon, title, description, optional action
 * - cards: Rich state with suggestion cards (like agent welcome screen)
 *
 * @example
 * // Simple variant
 * <EmptyStateVariant
 *   variant="simple"
 *   icon={Folder}
 *   title="No projects"
 *   description="Create your first project"
 *   action={<Button>Create Project</Button>}
 * />
 *
 * // Cards variant
 * <EmptyStateVariant
 *   variant="cards"
 *   title="How can I help?"
 *   subtitle="Your AI assistant is ready"
 *   cards={suggestionCards}
 *   onCardClick={(card) => handlePrompt(card.prompt)}
 * />
 */

import { memo, type FC, type ReactNode } from 'react';

import { Bot, ArrowRight } from 'lucide-react';

import type { LucideIcon } from 'lucide-react';

// ============================================================================
// TYPES
// ============================================================================

export interface SuggestionCard {
  /** Unique identifier */
  id: string;
  /** Card title */
  title: string;
  /** Card description */
  description: string;
  /** Icon to display */
  icon: ReactNode;
  /** Prompt/value to emit on click */
  prompt: string;
  /** Color theme: tailwind color name (blue, purple, emerald, amber, etc.) */
  color: string;
}

export interface EmptyStateSimpleProps {
  /** Icon to display */
  icon?: LucideIcon | undefined;
  /** Title text */
  title: string;
  /** Description text */
  description?: string | undefined;
  /** Optional action element (button) */
  action?: ReactNode | undefined;
  /** Center in container */
  centered?: boolean | undefined;
  /** Additional className */
  className?: string | undefined;
}

export interface EmptyStateCardsProps {
  /** Main title */
  title: string;
  /** Subtitle/description */
  subtitle?: string | undefined;
  /** Logo/icon to display above title */
  logo?: ReactNode | undefined;
  /** Suggestion cards */
  cards: SuggestionCard[];
  /** Card click handler */
  onCardClick?: ((card: SuggestionCard) => void) | undefined;
  /** Optional footer content */
  footer?: ReactNode | undefined;
  /** Optional resume/action card */
  resumeCard?: ReactNode | undefined;
  /** Additional context content */
  contextContent?: ReactNode | undefined;
  /** Additional className */
  className?: string | undefined;
}

export interface EmptyStateVariantProps {
  /** Variant to render */
  variant: 'simple' | 'cards';
  /** Shared props */
  title: string;
  /** Additional className */
  className?: string | undefined;
  /** Simple variant props */
  icon?: LucideIcon | undefined;
  description?: string | undefined;
  action?: ReactNode | undefined;
  centered?: boolean | undefined;
  /** Cards variant props */
  subtitle?: string | undefined;
  logo?: ReactNode | undefined;
  cards?: SuggestionCard[] | undefined;
  onCardClick?: ((card: SuggestionCard) => void) | undefined;
  footer?: ReactNode | undefined;
  resumeCard?: ReactNode | undefined;
  contextContent?: ReactNode | undefined;
}

// ============================================================================
// COLOR MAPPINGS
// ============================================================================

interface CardColors {
  gradient: string;
  iconColor: string;
  border: string;
  hoverBorder: string;
}

const CARD_COLOR_MAP: Record<string, CardColors> = {
  primary: {
    gradient: 'from-primary/8 to-primary/4',
    iconColor: 'text-primary',
    border: 'border-slate-200 dark:border-slate-700/50',
    hoverBorder: 'hover:border-slate-300 dark:hover:border-slate-600',
  },
  blue: {
    gradient: 'from-primary/8 to-primary/4',
    iconColor: 'text-primary',
    border: 'border-slate-200 dark:border-slate-700/50',
    hoverBorder: 'hover:border-slate-300 dark:hover:border-slate-600',
  },
  purple: {
    gradient: 'from-primary/8 to-primary/4',
    iconColor: 'text-primary',
    border: 'border-slate-200 dark:border-slate-700/50',
    hoverBorder: 'hover:border-slate-300 dark:hover:border-slate-600',
  },
  emerald: {
    gradient: 'from-primary/8 to-primary/4',
    iconColor: 'text-primary',
    border: 'border-slate-200 dark:border-slate-700/50',
    hoverBorder: 'hover:border-slate-300 dark:hover:border-slate-600',
  },
  amber: {
    gradient: 'from-primary/8 to-primary/4',
    iconColor: 'text-primary',
    border: 'border-slate-200 dark:border-slate-700/50',
    hoverBorder: 'hover:border-slate-300 dark:hover:border-slate-600',
  },
  slate: {
    gradient: 'from-slate-500/8 to-slate-500/4',
    iconColor: 'text-slate-500',
    border: 'border-slate-200 dark:border-slate-700/50',
    hoverBorder: 'hover:border-slate-300 dark:hover:border-slate-600',
  },
};

function getCardColors(color: string): CardColors {
  return CARD_COLOR_MAP[color] ?? CARD_COLOR_MAP.slate!;
}

// ============================================================================
// SIMPLE VARIANT
// ============================================================================

const EmptyStateSimpleComponent: FC<EmptyStateSimpleProps> = ({
  icon: Icon,
  title,
  description,
  action,
  centered = true,
  className = '',
}) => {
  const containerClass = centered
    ? 'flex flex-col items-center justify-center py-16 text-center'
    : 'py-8';

  return (
    <div className={`${containerClass} ${className}`}>
      {Icon && (
        <div
          className="
            w-14 h-14 rounded-2xl
            bg-slate-100 dark:bg-slate-800
            flex items-center justify-center mb-4
          "
        >
          <Icon size={28} className="text-slate-300 dark:text-slate-600" />
        </div>
      )}
      <h3 className="text-base font-medium text-slate-700 dark:text-slate-300 mb-1">{title}</h3>
      {description && (
        <p className="text-sm text-slate-400 dark:text-slate-500 max-w-sm mb-5">{description}</p>
      )}
      {action}
    </div>
  );
};

// ============================================================================
// CARDS VARIANT
// ============================================================================

const EmptyStateCardsComponent: FC<EmptyStateCardsProps> = ({
  title,
  subtitle,
  logo,
  cards,
  onCardClick,
  footer,
  resumeCard,
  contextContent,
  className = '',
}) => {
  const handleCardClick = (card: SuggestionCard) => {
    onCardClick?.(card);
  };

  return (
    <div
      className={`
        h-full w-full flex flex-col items-center justify-center
        p-6 overflow-y-auto relative
        ${className}
      `}
    >
      {/* Main Content */}
      <div className="text-center mb-10 relative z-10">
        {/* Logo/Icon */}
        {logo ?? (
          <div className="relative inline-block mb-6">
            <div
              className="
                relative w-16 h-16 rounded-xl
                bg-primary
                flex items-center justify-center shadow-md
              "
            >
              <Bot size={32} className="text-white" />
            </div>
          </div>
        )}

        {/* Title */}
        <h1 className="text-3xl font-bold text-slate-900 dark:text-slate-100 mb-3">{title}</h1>

        {/* Subtitle */}
        {subtitle && (
          <p className="text-slate-500 dark:text-slate-400 max-w-md mx-auto mb-8 text-base leading-relaxed">
            {subtitle}
          </p>
        )}
      </div>

      {/* Resume Card */}
      {resumeCard && <div className="max-w-2xl w-full relative z-10 mb-4">{resumeCard}</div>}

      {/* Context Content */}
      {contextContent && (
        <div className="space-y-4 mb-6 max-w-2xl w-full relative z-10">
          {contextContent}
        </div>
      )}

      {/* Suggestion Cards */}
      {cards && cards.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-2xl w-full relative z-10">
          {cards.map((card) => {
            const colors = getCardColors(card.color);
            return (
              <button
                key={card.id}
                type="button"
                onClick={() => { handleCardClick(card); }}
                className={`
                  group relative p-4 rounded-xl
                  bg-white dark:bg-slate-800/50
                  border ${colors.border} ${colors.hoverBorder}
                  hover:shadow-md
                  transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-200 ease-out
                  text-left
                `}
              >
                <div className="flex items-start justify-between mb-3">
                  <div
                    className={`
                      w-10 h-10 rounded-lg
                      bg-primary/8 dark:bg-primary/15
                      flex items-center justify-center
                      ${colors.iconColor}
                    `}
                  >
                    {card.icon}
                  </div>
                  <ArrowRight
                    size={14}
                    className="
                      text-slate-300 dark:text-slate-600
                      opacity-0 group-hover:opacity-100
                      group-hover:translate-x-0.5
                      transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-200
                    "
                  />
                </div>

                <h3 className="font-medium text-slate-900 dark:text-slate-100 mb-1 text-sm">
                  {card.title}
                </h3>

                <p className="text-xs text-slate-400 dark:text-slate-500 leading-relaxed">
                  {card.description}
                </p>
              </button>
            );
          })}
        </div>
      )}

      {/* Footer */}
      {footer && (
        <div className="mt-10 text-center relative z-10">{footer}</div>
      )}
    </div>
  );
};

// ============================================================================
// MAIN COMPONENT
// ============================================================================

const EmptyStateVariantComponent: FC<EmptyStateVariantProps> = ({
  variant,
  className = '',
  ...props
}) => {
  if (variant === 'cards') {
    return (
      <EmptyStateCardsComponent
        title={props.title}
        subtitle={props.subtitle}
        logo={props.logo}
        cards={props.cards ?? []}
        onCardClick={props.onCardClick}
        footer={props.footer}
        resumeCard={props.resumeCard}
        contextContent={props.contextContent}
        className={className}
      />
    );
  }

  return (
    <EmptyStateSimpleComponent
      icon={props.icon}
      title={props.title}
      description={props.description}
      action={props.action}
      centered={props.centered}
      className={className}
    />
  );
};

// Memoized exports
export const EmptyStateVariant = memo(EmptyStateVariantComponent);
export const EmptyStateSimple = memo(EmptyStateSimpleComponent);
export const EmptyStateCards = memo(EmptyStateCardsComponent);

EmptyStateVariant.displayName = 'EmptyStateVariant';
EmptyStateSimple.displayName = 'EmptyStateSimple';
EmptyStateCards.displayName = 'EmptyStateCards';
