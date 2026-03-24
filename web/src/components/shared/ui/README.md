# Design System Components

Extracted reusable UI components for MemStack.

## StatusBadge

Status indicator with consistent styling across the application.

```tsx
import { StatusBadge } from '@/components/shared';

// Basic usage
<StatusBadge status="running" label="Processing" />
<StatusBadge status="success" label="Complete" duration={1234} />
<StatusBadge status="error" label="Failed" />
<StatusBadge status="warning" label="Retry" />
<StatusBadge status="idle" label="Ready" />

// Props
interface StatusBadgeProps {
  status: 'running' | 'success' | 'error' | 'warning' | 'idle';
  label?: string;           // Optional custom label (defaults to status)
  duration?: number;        // Optional duration in ms (shown for success)
  size?: 'sm' | 'md';       // Size variant (default: 'sm')
  className?: string;       // Additional className
  animate?: boolean;        // Show animated pulse for running state (default: true)
}
```

### Color Mapping

| Status   | Background           | Text                    | Indicator        |
|----------|---------------------|-------------------------|------------------|
| running  | blue-50/blue-500/10 | blue-600/blue-400       | Animated pulse   |
| success  | emerald-50/500/10   | emerald-600/emerald-400 | CheckCircle icon |
| error    | red-50/red-500/10   | red-600/red-400         | AlertCircle icon |
| warning  | amber-50/amber/10   | amber-600/amber-400     | AlertTriangle    |
| idle     | slate-50/slate/10   | slate-500/slate-400     | Circle icon      |

---

## StateDisplay

Compound component for Loading/Empty/Error states.

```tsx
import { StateDisplay } from '@/components/shared';

// Loading state
<StateDisplay.Loading message="Loading projects..." />
<StateDisplay.Loading size="lg" card={false} />

// Empty state
<StateDisplay.Empty
  icon={Folder}
  title="No projects"
  description="Create your first project to get started"
  action={<Button>Create Project</Button>}
/>

// Error state
<StateDisplay.Error
  error={error}
  title="Something went wrong"
  onRetry={handleRetry}
  onDismiss={handleDismiss}
/>
```

### Props

#### StateLoadingProps
```tsx
interface StateLoadingProps {
  message?: string;           // Optional loading message
  size?: 'sm' | 'md' | 'lg';  // Size variant (default: 'md')
  card?: boolean;             // Use card wrapper (default: true)
  className?: string;
}
```

#### StateEmptyProps
```tsx
interface StateEmptyProps {
  icon?: LucideIcon;          // Icon to display (default: Inbox)
  title: string;              // Title text (required)
  description?: string;       // Description text
  action?: ReactNode;         // Action button element
  card?: boolean;             // Use card wrapper (default: true)
  className?: string;
}
```

#### StateErrorProps
```tsx
interface StateErrorProps {
  error?: string | Error;     // Error message or object
  title?: string;             // Title for error (default: "Something went wrong")
  onRetry?: () => void;       // Retry callback
  onDismiss?: () => void;     // Dismiss callback
  card?: boolean;             // Use card wrapper (default: true)
  className?: string;
}
```

---

## EmptyStateVariant

Flexible empty state with simple and cards variants.

```tsx
import { EmptyStateVariant, EmptyStateSimple, EmptyStateCards } from '@/components/shared';
import type { SuggestionCard } from '@/components/shared';

// Simple variant (basic centered state)
<EmptyStateVariant
  variant="simple"
  icon={Folder}
  title="No projects"
  description="Create your first project"
  action={<Button onClick={onCreate}>Create Project</Button>}
/>

// Cards variant (rich welcome screen)
const cards: SuggestionCard[] = [
  {
    id: 'trends',
    title: 'Analyze trends',
    description: 'Identify patterns in your data',
    icon: <BarChart3 size={20} />,
    prompt: 'Analyze the trends in my project',
    color: 'blue',
  },
  // ...more cards
];

<EmptyStateVariant
  variant="cards"
  title="How can I help you today?"
  subtitle="Your AI assistant is ready"
  cards={cards}
  onCardClick={(card) => sendPrompt(card.prompt)}
/>

// Direct component usage
<EmptyStateSimple title="No results" description="Try a different search" />
<EmptyStateCards title="Welcome" cards={cards} onCardClick={handleClick} />
```

### SuggestionCard Type
```tsx
interface SuggestionCard {
  id: string;           // Unique identifier
  title: string;        // Card title
  description: string;  // Card description
  icon: ReactNode;      // Icon element
  prompt: string;       // Prompt/value to emit on click
  color: string;        // Color theme: blue, purple, emerald, amber, slate, primary
}
```

### Available Card Colors

| Color   | Icon Color    | Border Style                          |
|---------|--------------|---------------------------------------|
| blue    | text-blue-500 | blue-200/blue-800                    |
| purple  | text-purple-500 | purple-200/purple-800              |
| emerald | text-emerald-500 | emerald-200/emerald-800           |
| amber   | text-amber-500 | amber-200/amber-800                 |
| slate   | text-slate-500 | slate-200/slate-800                 |
| primary | text-primary  | primary-200/primary-800              |

---

## Usage Patterns

### Conditional State Rendering
```tsx
function ProjectList({ isLoading, error, projects }) {
  if (isLoading) {
    return <StateDisplay.Loading message="Loading projects..." />;
  }

  if (error) {
    return <StateDisplay.Error error={error} onRetry={refetch} />;
  }

  if (projects.length === 0) {
    return (
      <EmptyStateSimple
        icon={Folder}
        title="No projects"
        description="Create your first project"
        action={<Button onClick={onCreate}>Create</Button>}
      />
    );
  }

  return <ProjectGrid projects={projects} />;
}
```

### Tool Execution Status
```tsx
function ToolCard({ toolExecution }) {
  return (
    <div className="p-4 border rounded-lg">
      <div className="flex items-center justify-between">
        <span>{toolExecution.name}</span>
        <StatusBadge
          status={toolExecution.status}
          duration={toolExecution.duration}
        />
      </div>
    </div>
  );
}
```

---

## Files

- `StatusBadge.tsx` - Status indicator component
- `StateDisplay.tsx` - Loading/Empty/Error states compound component
- `EmptyStateVariant.tsx` - Flexible empty state with variants

## Design Tokens Used

All components use design tokens from `index.css`:
- `--color-primary`: #1e3fae
- `--color-primary-600`: Darker primary
- Standard Tailwind colors for status variants
