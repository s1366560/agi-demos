# AppSidebar Module

A refactored sidebar component system using explicit variant components and compound components pattern.

## API

```tsx
// Option 1: Explicit variant components (recommended)
import { TenantSidebar } from '@/components/layout/AppSidebar'

<TenantSidebar tenantId="tenant-123" />

// Option 2: Use AppSidebar with variant prop
import { AppSidebar } from '@/components/layout/AppSidebar'

<AppSidebar
  config={config}
  basePath="/tenant"
  variant="tenant"  // explicit variant prop
  user={user}
/>

// Option 3: Compound components (for advanced customization)
import { AppSidebar, SidebarBrand, SidebarNavigation, SidebarUser } from '@/components/layout/AppSidebar'

<AppSidebar basePath="/tenant" user={user}>
  <SidebarBrand variant="tenant" />
  <SidebarNavigation config={config} />
  <SidebarUser user={user} onLogout={handleLogout} />
</AppSidebar>
```

## Component Exports

### Main Components

- `AppSidebar` - Main sidebar with variant prop support
- `TenantSidebar` - Tenant-level sidebar with embedded config
- `ProjectSidebar` - Project-level sidebar with embedded config
- `AgentSidebar` - Agent-level sidebar with embedded config

### Compound Components

- `SidebarBrand` - Brand/logo section
- `SidebarNavigation` - Navigation groups with collapsible support
- `SidebarUser` - User profile section
- `SidebarNavItem` - Individual navigation item

### Context and Hooks

- `SidebarContext` - Context for compound components
- `useSidebarContext` - Hook to access sidebar context

### Types

- `SidebarVariant` - Union type: 'tenant' | 'project' | 'agent'
- `BaseSidebarProps` - Common props for all sidebar variants
- `AppSidebarProps` - Props for main AppSidebar component
- `TenantSidebarProps` - Props for TenantSidebar
- `ProjectSidebarProps` - Props for ProjectSidebar
- `AgentSidebarProps` - Props for AgentSidebar

## Features

1. **Explicit Variants** - No more context prop switching, use dedicated components
2. **Type Safety** - Each variant has its own prop interface
3. **Compound Pattern** - Compose sidebar sections as needed
4. **React 19 Best Practices** - Uses modern React patterns
5. **80%+ Test Coverage** - Comprehensive test suite

## File Structure

```
src/components/layout/AppSidebar/
├── index.tsx              # Main exports
├── AppSidebar.tsx         # Root component
├── TenantSidebar.tsx      # Tenant variant
├── ProjectSidebar.tsx     # Project variant
├── AgentSidebar.tsx       # Agent variant
├── SidebarBrand.tsx       # Brand section
├── SidebarNavigation.tsx  # Navigation section
├── SidebarUser.tsx        # User section
├── SidebarNavItem.tsx     # Navigation item
├── SidebarContext.tsx     # Shared context
└── types.ts               # Type definitions
```

## Tests

- 68 tests pass across all sidebar components
- 80%+ code coverage
- Located in `src/test/components/layout/AppSidebar/`
