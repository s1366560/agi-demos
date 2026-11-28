import type { ReviewTab } from '../../appShellTypes';

export type WorkPanelTab = ReviewTab | 'browser' | 'run-details';
export type WorkPanelState = Readonly<{
  tabs: readonly WorkPanelTab[];
  active: WorkPanelTab | null;
  open: boolean;
}>;
export const EMPTY_WORK_PANEL: WorkPanelState = {
  tabs: [],
  active: null,
  open: false,
};
export type WorkPanelAction =
  | { type: 'open' | 'select'; tab: WorkPanelTab }
  | { type: 'close'; tab: WorkPanelTab }
  | { type: 'hide' }
  | { type: 'show'; fallback: WorkPanelTab };

export function normalizeWorkPanelTab(tab: WorkPanelTab): WorkPanelTab {
  return tab === 'pull' ? 'checks' : tab === 'background' ? 'activity' : tab;
}

export function reduceWorkPanel(state: WorkPanelState, action: WorkPanelAction): WorkPanelState {
  if (action.type === 'hide') return { ...state, open: false };
  if (action.type === 'show') {
    return state.active
      ? { ...state, open: true }
      : reduceWorkPanel(state, { type: 'open', tab: action.fallback });
  }
  const tab = normalizeWorkPanelTab(action.tab);
  if (action.type === 'close') {
    const index = state.tabs.indexOf(tab);
    if (index < 0) return state;
    const tabs = state.tabs.filter((candidate) => candidate !== tab);
    return {
      tabs,
      active:
        state.active === tab ? (tabs[Math.min(index, tabs.length - 1)] ?? null) : state.active,
      open: state.open && tabs.length > 0,
    };
  }
  return {
    tabs: state.tabs.includes(tab) ? state.tabs : [...state.tabs, tab],
    active: tab,
    open: action.type === 'open' || state.open,
  };
}

export function workPanelGeometry(
  availableWidth: number,
  preferredWidth: number | null,
  focused: boolean,
) {
  const available = Math.max(0, availableWidth);
  const fullWidth = focused || available < 840;
  const max = Math.max(360, Math.min(available * 0.6, available - 480));
  const constraints = {
    min: 360,
    max,
    default: Math.min(max, Math.max(360, available * 0.4)),
  };
  return {
    fullWidth,
    constraints,
    width: fullWidth
      ? available
      : Math.min(max, Math.max(360, preferredWidth ?? constraints.default)),
  };
}
