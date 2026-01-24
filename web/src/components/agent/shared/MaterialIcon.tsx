/**
 * MaterialIcon - Wrapper for Material Symbols Outlined icons
 *
 * Provides consistent styling and behavior for Material Design icons.
 * Uses the material-symbols package which loads Google's Material Symbols.
 */

import { forwardRef, type ComponentProps } from 'react';

export interface MaterialIconProps extends Omit<ComponentProps<'span'>, 'ref'> {
  /**
   * The icon name from Material Symbols Outlined
   * @see https://fonts.google.com/icons
   */
  name: string;

  /**
   * Icon size in pixels (default: 24)
   */
  size?: number;

  /**
   * Icon weight (default: 400, regular)
   */
  weight?: number;

  /**
   * Whether the icon should be filled (default: false, outlined)
   */
  filled?: boolean;

  /**
   * Optional CSS class for additional styling
   */
  className?: string;
}

/**
 * MaterialIcon component renders Material Symbols Outlined icons
 *
 * @example
 * <MaterialIcon name="search" />
 * <MaterialIcon name="home" size={20} filled />
 * <MaterialIcon name="settings" weight={700} className="text-primary" />
 */
export const MaterialIcon = forwardRef<HTMLSpanElement, MaterialIconProps>(
  ({ name, size = 24, weight = 400, filled = false, className = '', ...props }, ref) => {
    const fontVariationSettings = `${filled ? 'FILL' : '0'} ${weight} 0 24`;

    return (
      <span
        ref={ref}
        className={`material-symbols-outlined ${className}`}
        style={{
          fontVariationSettings,
          fontSize: `${size}px`,
          lineHeight: '1',
          ...props.style,
        }}
        {...props}
      >
        {name}
      </span>
    );
  }
);

MaterialIcon.displayName = 'MaterialIcon';

export default MaterialIcon;
