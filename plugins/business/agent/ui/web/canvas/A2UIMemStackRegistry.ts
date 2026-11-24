import {
  ComponentRegistry,
  initializeDefaultCatalog,
  type A2UIComponentRegistry,
} from "./a2uiInternals";
import {
  A2UIButton,
  A2UICard,
  A2UIColumn,
  A2UIList,
  A2UIModal,
  A2UIRow,
  A2UITabs,
} from "./A2UIIsolatedComponents";
import { A2UIProgress } from "./A2UIProgress";
import { A2UIRadio } from "./A2UIRadio";
import { A2UITable } from "./A2UITable";

function registerMemStackA2UIComponents(registry: A2UIComponentRegistry): void {
  registry.register("Row", { component: A2UIRow });
  registry.register("Column", { component: A2UIColumn });
  registry.register("List", { component: A2UIList });
  registry.register("Card", { component: A2UICard });
  registry.register("Tabs", { component: A2UITabs });
  registry.register("Modal", { component: A2UIModal });
  registry.register("Button", { component: A2UIButton });
  registry.register("Radio", { component: A2UIRadio });
  registry.register("Progress", { component: A2UIProgress });
  registry.register("Table", { component: A2UITable });
}

export function ensureMemStackA2UIRegistry(): void {
  initializeDefaultCatalog();
  const registry = ComponentRegistry.getInstance();
  registerMemStackA2UIComponents(registry);
}

export function createMemStackA2UIRegistry(): A2UIComponentRegistry {
  initializeDefaultCatalog();

  const baseRegistry = ComponentRegistry.getInstance();
  const registry = new ComponentRegistry();

  for (const type of baseRegistry.getRegisteredTypes()) {
    const component = baseRegistry.get(type);
    if (component) {
      registry.register(type, { component });
    }
  }

  registerMemStackA2UIComponents(registry);
  return registry;
}
