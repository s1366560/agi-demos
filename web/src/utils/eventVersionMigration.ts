/**
 * Event Version Migration
 * 
 * Handles migration of event payloads between schema versions.
 * Uses BFS to find the shortest migration path between versions.
 */

import { CURRENT_SCHEMA_VERSION } from '../types/generated/eventEnvelope';

import type { AgentEventType } from '../types/generated/eventTypes';

// =============================================================================
// Types
// =============================================================================

/**
 * Migration function type
 */
type MigrationFn = (data: unknown) => unknown;

/**
 * Version migration definition
 */
interface VersionMigration {
  from: string;
  to: string;
  migrate: MigrationFn;
}

// =============================================================================
// Migration Registry
// =============================================================================

/**
 * Registry of migrations per event type
 * Key: event type
 * Value: array of version migrations
 */
const migrationRegistry = new Map<AgentEventType, VersionMigration[]>();

/**
 * Register a migration for an event type
 */
export function registerMigration(
  eventType: AgentEventType,
  from: string,
  to: string,
  migrate: MigrationFn
): void {
  const migrations = migrationRegistry.get(eventType) || [];
  migrations.push({ from, to, migrate });
  migrationRegistry.set(eventType, migrations);
}

/**
 * Register multiple migrations at once
 */
export function registerMigrations(
  eventType: AgentEventType,
  migrations: VersionMigration[]
): void {
  const existing = migrationRegistry.get(eventType) || [];
  migrationRegistry.set(eventType, [...existing, ...migrations]);
}

// =============================================================================
// Migration Path Finding (BFS)
// =============================================================================

/**
 * Find the shortest migration path between versions using BFS
 */
function findMigrationPath(
  eventType: AgentEventType,
  fromVersion: string,
  toVersion: string
): MigrationFn[] | null {
  if (fromVersion === toVersion) {
    return [];
  }

  const migrations = migrationRegistry.get(eventType);
  if (!migrations || migrations.length === 0) {
    return null;
  }

  // Build adjacency list
  const adjacency = new Map<string, { to: string; migrate: MigrationFn }[]>();
  for (const m of migrations) {
    const edges = adjacency.get(m.from) || [];
    edges.push({ to: m.to, migrate: m.migrate });
    adjacency.set(m.from, edges);
  }

  // BFS to find shortest path
  const queue: { version: string; path: MigrationFn[] }[] = [
    { version: fromVersion, path: [] },
  ];
  const visited = new Set<string>([fromVersion]);

  while (queue.length > 0) {
    const { version, path } = queue.shift()!;

    const edges = adjacency.get(version) || [];
    for (const edge of edges) {
      if (edge.to === toVersion) {
        return [...path, edge.migrate];
      }

      if (!visited.has(edge.to)) {
        visited.add(edge.to);
        queue.push({
          version: edge.to,
          path: [...path, edge.migrate],
        });
      }
    }
  }

  return null; // No path found
}

// =============================================================================
// Migration Execution
// =============================================================================

/**
 * Migrate event data from one version to another
 * 
 * @param eventType - The event type
 * @param data - The event payload
 * @param fromVersion - Source schema version
 * @param toVersion - Target schema version (defaults to current)
 * @returns Migrated data, or original if no migration needed/available
 */
export function migrateEventData<T = unknown>(
  eventType: AgentEventType,
  data: T,
  fromVersion: string,
  toVersion: string = CURRENT_SCHEMA_VERSION
): T {
  // No migration needed
  if (fromVersion === toVersion) {
    return data;
  }

  // Find migration path
  const path = findMigrationPath(eventType, fromVersion, toVersion);
  
  if (!path) {
    console.warn(
      `No migration path found for ${eventType} from ${fromVersion} to ${toVersion}`
    );
    return data;
  }

  // Apply migrations in sequence
  let result: unknown = data;
  for (const migrate of path) {
    result = migrate(result);
  }

  return result as T;
}

/**
 * Check if a migration path exists
 */
export function canMigrate(
  eventType: AgentEventType,
  fromVersion: string,
  toVersion: string = CURRENT_SCHEMA_VERSION
): boolean {
  if (fromVersion === toVersion) return true;
  return findMigrationPath(eventType, fromVersion, toVersion) !== null;
}

/**
 * Get all registered event types with migrations
 */
export function getMigratableEventTypes(): AgentEventType[] {
  return Array.from(migrationRegistry.keys());
}

// =============================================================================
// Built-in Migrations
// =============================================================================

/**
 * Initialize built-in migrations for core event types
 */
export function initializeBuiltinMigrations(): void {
  // Thought event migrations
  registerMigrations('thought', [
    {
      from: '1.0',
      to: '1.1',
      migrate: (data) => {
        const d = data as Record<string, unknown>;
        return {
          ...d,
          level: d.level || 'work', // Add default level
        };
      },
    },
    {
      from: '1.1',
      to: '2.0',
      migrate: (data) => {
        const d = data as Record<string, unknown>;
        return {
          ...d,
          thinking_chain: d.thinking_chain || [], // Add thinking chain
          metadata: {
            ...(d.metadata as Record<string, unknown> || {}),
            migrated_from: '1.1',
          },
        };
      },
    },
  ]);

  // Act event migrations
  registerMigrations('act', [
    {
      from: '1.0',
      to: '1.1',
      migrate: (data) => {
        const d = data as Record<string, unknown>;
        return {
          ...d,
          execution_id: d.execution_id || `exec_${Date.now()}`,
        };
      },
    },
  ]);

  // Observe event migrations
  registerMigrations('observe', [
    {
      from: '1.0',
      to: '1.1',
      migrate: (data) => {
        const d = data as Record<string, unknown>;
        // Normalize 'observation' to 'result'
        if ('observation' in d && !('result' in d)) {
          const { observation, ...rest } = d;
          return {
            ...rest,
            result: observation,
          };
        }
        return d;
      },
    },
  ]);

  // Work plan event migrations
  registerMigrations('work_plan', [
    {
      from: '1.0',
      to: '1.1',
      migrate: (data) => {
        const d = data as Record<string, unknown>;
        const steps = d.steps as Array<Record<string, unknown>> || [];
        return {
          ...d,
          steps: steps.map((step, index) => ({
            ...step,
            step_number: step.step_number ?? index + 1,
            status: step.status || 'pending',
          })),
        };
      },
    },
  ]);

  // Message event migrations
  registerMigrations('message', [
    {
      from: '1.0',
      to: '1.1',
      migrate: (data) => {
        const d = data as Record<string, unknown>;
        return {
          ...d,
          artifacts: d.artifacts || [],
        };
      },
    },
  ]);

  // Complete event migrations
  registerMigrations('complete', [
    {
      from: '1.0',
      to: '1.1',
      migrate: (data) => {
        const d = data as Record<string, unknown>;
        return {
          ...d,
          artifacts: d.artifacts || [],
          trace_url: d.trace_url || null,
        };
      },
    },
  ]);

  // HITL event migrations
  registerMigrations('clarification_asked', [
    {
      from: '1.0',
      to: '1.1',
      migrate: (data) => {
        const d = data as Record<string, unknown>;
        return {
          ...d,
          clarification_type: d.clarification_type || 'text_input',
          allow_custom: d.allow_custom ?? true,
        };
      },
    },
  ]);

  registerMigrations('permission_asked', [
    {
      from: '1.0',
      to: '1.1',
      migrate: (data) => {
        const d = data as Record<string, unknown>;
        return {
          ...d,
          risk_level: d.risk_level || 'medium',
          allow_remember: d.allow_remember ?? false,
        };
      },
    },
  ]);
}

// Initialize built-in migrations on module load
initializeBuiltinMigrations();

// =============================================================================
// Export
// =============================================================================

export default {
  migrateEventData,
  canMigrate,
  registerMigration,
  registerMigrations,
  getMigratableEventTypes,
  initializeBuiltinMigrations,
};
