# MemStack Design Context

## Users

Enterprise developers and technical professionals who use AI agents as collaborative partners. They work with complex multi-layer agent systems (Tool -> Skill -> SubAgent -> Agent) and need to:
- Monitor agent reasoning and execution
- Manage knowledge graphs and memories
- Configure and orchestrate specialized subagents
- Review artifacts and execution traces

They use the platform for extended periods, often switching between detailed technical work and high-level overviews.

## Brand Personality

**Clean, Minimal, Technical**

Vercel-inspired aesthetic: black/white/gray palette, function-first, zero visual noise. Every pixel serves a purpose. The interface should feel like a precision tool, not a consumer app.

- **Confidence & Precision**: Crisp typography, tight spacing, no decorative elements
- **Voice**: Direct, technical, efficient - every word earns its place
- **Tone**: Calm competence, understated authority, technical depth without complexity

## Aesthetic Direction

**Vercel Design Language** - extracted from vercel.com (March 2026)

### Core Visual Identity
- **Monochrome Foundation**: Black `#000` / `#171717` text on white `#fff` / `#fafafa` backgrounds
- **10-Level Gray Scale**: `#111` to `#fafafa` (accents-1 through accents-8 + foreground/background)
- **Blue Accent**: `#0070f3` (success/link color), used sparingly for CTAs and interactive highlights
- **Geist Typography**: Tight letter-spacing on headings, clean body text at 16px

### Anti-References
- **NOT playful/consumer apps**: Avoid over-the-top colors, whimsical illustrations, gamification
- **NOT cluttered enterprise**: Avoid dense dashboards with competing widgets
- **NOT legacy software**: Avoid dated UI patterns, heavy chrome, complex navigation
- **NOT gradient-heavy**: Avoid heavy glass morphism, colored backgrounds, decorative blurs

### Theme Support
- **Light mode**: Pure white backgrounds, black text, light gray borders `#eaeaea`
- **Dark mode**: Pure black/near-black surfaces, white text, dark gray borders

## Design Principles

1. **Clarity Over Cleanness**: Prioritize readable information hierarchy over minimalist aesthetics. Technical content should be scannable. Vercel uses tight negative letter-spacing on headings for maximum legibility.

2. **Zero Visual Noise**: Remove decorative elements. Borders are 1px, shadows are barely visible (0.08 alpha), backgrounds are solid colors. Every visual element must convey information.

3. **Pill-Shape CTAs**: Primary actions use pill-shaped buttons (border-radius: 100px, height: 48px). Secondary actions use white bg with dark text and same pill shape. Navigation uses rounded-pill ghost buttons.

4. **Progressive Disclosure**: Show essential information first. Complex details (execution traces, tool outputs) available on demand. Status badges use 11px uppercase text in pill shapes.

5. **Consistent Component Language**: All components share the same lower-radius system (4px default controls, 6px structural surfaces), border-only shadows with 0.08 alpha, a 4px spacing base, and a 36px default app-button/form-control height. Reserve pill shapes for explicit CTAs, nav pills, and compact badges only.

## Vercel Design System Reference

### Typography
```css
--font-sans: 'Geist', Arial, sans-serif
--font-mono: 'Geist Mono', ui-monospace, monospace

/* Headings - tight negative tracking */
h1: 48px / 600 / 48px line-height / -2.4px letter-spacing
h2: 24px / 600 / 32px line-height / -0.96px letter-spacing
h3: 12px / 500 / 12px line-height (section labels, uppercase)

/* Body */
body: 16px / 400 / normal line-height
small: 14px / 400 (nav, secondary text)
badge: 11px / 500 (status pills)
```

### Gray Scale (Light Mode)
```css
--accents-1: #fafafa   /* lightest background */
--accents-2: #eaeaea   /* borders, dividers */
--accents-3: #999999   /* muted text */
--accents-4: #888888   /* secondary text */
--accents-5: #666666   /* body secondary */
--accents-6: #444444   /* emphasized text */
--accents-7: #333333   /* headings secondary */
--accents-8: #111111   /* near-black text */
--foreground: #000000  /* primary text */
--background: #ffffff  /* page background */
```

### Semantic Colors
```css
--success: #0070f3     /* blue - links, active, primary CTA */
--success-light: #3291ff
--success-dark: #0761d1
--error: #ee0000
--warning: #f5a623
--violet: #7928ca      /* accent for highlights */
--cyan: #50e3c2        /* accent for code/highlights */
```

### Spacing (4px Base Unit)
```css
--geist-space: 4px
--geist-space-2x: 8px
--geist-space-3x: 12px
--geist-space-4x: 16px
--geist-space-6x: 24px
--geist-space-8x: 32px
--geist-space-10x: 40px
--geist-space-16x: 64px
--geist-space-24x: 96px
```

### Border Radius
```css
--geist-radius: 4px           /* default controls */
--geist-marketing-radius: 6px /* structural cards */
pill: 9999px                  /* badges, small tags */
cta-pill: 100px               /* CTA buttons */
```

### Shadows (Minimal)
```css
--ds-shadow-border: 0 0 0 1px rgba(0,0,0,0.08)   /* card border */
--ds-shadow-small: 0 2px 2px rgba(0,0,0,0.04)     /* slight lift */
--ds-shadow-medium: 0 2px 2px rgba(0,0,0,0.04), 0 8px 8px -8px rgba(0,0,0,0.04)
--ds-shadow-menu: border + 0 4px 8px -4px rgba(0,0,0,0.04), 0 16px 24px -8px rgba(0,0,0,0.06)
```

### Component Patterns

#### Primary Button (CTA)
- Background: `#171717` (near-black)
- Text: `#ffffff` white, 16px, weight 500
- Border-radius: 100px (pill)
- Height: 48px, padding: 0 14px

#### Secondary Button
- Background: `#ffffff` white
- Text: `#171717` dark, 16px, weight 500
- Border-radius: 100px (pill)
- Height: 48px, padding: 0 14px

#### Default App Button
- Background: theme-driven monochrome variants
- Text: theme-driven contrast colors
- Border-radius: 4px
- Height: 36px
- Use for the main product UI, forms, tables, and canvas actions

#### Ghost Button (Nav)
- Background: transparent
- Text: `#4d4d4d` gray, 14px, weight 400
- Border-radius: 9999px (pill)
- Height: 30px, padding: 8px 12px

#### Input Field
- Background: `#ffffff`
- Border: 1px solid `#eaeaea`
- Border-radius: 4px
- Height: 36px, padding: 0 12px
- Font: 14px, weight 400

#### Badge/Tag
- Background: `#ebebeb` light gray
- Text: `#171717`, 11px, weight 500
- Border-radius: 9999px (pill)
- Padding: 0 8px
- Status variant: white bg + colored dot

#### Card
- Background: `#ffffff`
- Border-radius: 6px
- Box-shadow: 0 0 0 1px rgba(0,0,0,0.08) + subtle inner shadow
- No visible border

### Focus Ring
```css
--ds-focus: 0 0 0 1px var(--ds-gray-alpha-600), 0 0 0 4px rgba(0,0,0,0.16)
```

## Implementation Notes

### Typography
- **Display/Body**: Geist (or Inter as fallback) - tight letter-spacing on headings
- **Monospace**: Geist Mono (or JetBrains Mono as fallback)
- **Scale**: 12px (badges) -> 14px (body small) -> 16px (body) -> 24px (h2) -> 48px (h1)

### Color Token Migration
The existing `#1e3fae` primary blue should transition to Vercel's `#0070f3` (lighter, more vibrant). The gray scale should shift from slate tones to pure neutral grays.

### Spacing
4px base unit (same as current): 4, 8, 12, 16, 24, 32, 40, 64, 96

### Accessibility
- Target: WCAG 2.1 AA compliance
- Current: High contrast mode, reduced motion support, focus rings
- Required: Color contrast ratios, keyboard navigation, ARIA labels
- Vercel focus ring: 1px gray ring + 4px transparent outer ring

### Animation
- **Enter**: minimal - fade-in (0.15s), subtle slide
- **Hover**: background color shift, no scale transforms
- **Loading**: minimal spinner or text-based indicators
- **Reduced motion**: All animations respect `prefers-reduced-motion`

## Reference Files

- Design tokens: `web/src/index.css`
- Component patterns: `web/src/components/agent/`
- Coding standards: `CLAUDE.md`
