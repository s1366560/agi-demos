import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

export const LABEL_COLORS = [
  {
    name: 'red',
    bg: 'bg-red-100 dark:bg-red-900/30',
    text: 'text-red-700 dark:text-red-300',
    dot: 'bg-red-500',
  },
  {
    name: 'blue',
    bg: 'bg-blue-100 dark:bg-blue-900/30',
    text: 'text-blue-700 dark:text-blue-300',
    dot: 'bg-blue-500',
  },
  {
    name: 'green',
    bg: 'bg-green-100 dark:bg-green-900/30',
    text: 'text-green-700 dark:text-green-300',
    dot: 'bg-green-500',
  },
  {
    name: 'purple',
    bg: 'bg-purple-100 dark:bg-purple-900/30',
    text: 'text-purple-700 dark:text-purple-300',
    dot: 'bg-purple-500',
  },
  {
    name: 'amber',
    bg: 'bg-amber-100 dark:bg-amber-900/30',
    text: 'text-amber-700 dark:text-amber-300',
    dot: 'bg-amber-500',
  },
  {
    name: 'pink',
    bg: 'bg-pink-100 dark:bg-pink-900/30',
    text: 'text-pink-700 dark:text-pink-300',
    dot: 'bg-pink-500',
  },
] as const;

export type LabelColor = (typeof LABEL_COLORS)[number]['name'];

export interface ConversationLabel {
  id: string;
  name: string;
  color: LabelColor;
}

interface ConversationLabelsState {
  conversationLabels: Record<string, string[]>;
  labels: ConversationLabel[];
  addLabel: (label: ConversationLabel) => void;
  removeLabel: (labelId: string) => void;
  toggleConversationLabel: (conversationId: string, labelId: string) => void;
  getLabelsForConversation: (conversationId: string) => ConversationLabel[];
}

export const useConversationLabelsStore = create<ConversationLabelsState>()(
  devtools(
    persist(
      (set, get) => ({
        conversationLabels: {},
        labels: [],

        addLabel: (label) =>
          set((state) => ({ labels: [...state.labels, label] }), false, 'addLabel'),

        removeLabel: (labelId) =>
          set(
            (state) => {
              const newConversationLabels: Record<string, string[]> = {};
              for (const [convId, labelIds] of Object.entries(state.conversationLabels)) {
                const filtered = labelIds.filter((id) => id !== labelId);
                if (filtered.length > 0) {
                  newConversationLabels[convId] = filtered;
                }
              }
              return {
                labels: state.labels.filter((l) => l.id !== labelId),
                conversationLabels: newConversationLabels,
              };
            },
            false,
            'removeLabel'
          ),

        toggleConversationLabel: (conversationId, labelId) =>
          set(
            (state) => {
              const current = state.conversationLabels[conversationId] ?? [];
              const exists = current.includes(labelId);
              const updated = exists
                ? current.filter((id) => id !== labelId)
                : [...current, labelId];
              return {
                conversationLabels: {
                  ...state.conversationLabels,
                  [conversationId]: updated,
                },
              };
            },
            false,
            'toggleConversationLabel'
          ),

        getLabelsForConversation: (conversationId) => {
          const state = get();
          const labelIds = state.conversationLabels[conversationId] ?? [];
          return labelIds
            .map((id) => state.labels.find((l) => l.id === id))
            .filter((l): l is ConversationLabel => l != null);
        },
      }),
      { name: 'conversation-labels' }
    ),
    { name: 'conversation-labels-store' }
  )
);
