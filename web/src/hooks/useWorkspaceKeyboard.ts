import { useEffect } from "react";

import { useAgentV3Store } from "@/stores/agentV3";

interface WorkspaceKeyboardOpts {
	inputBarRef: React.RefObject<HTMLTextAreaElement | null>;
	onToggleChatSearch: () => void;
}

export function useWorkspaceKeyboard({
	inputBarRef,
	onToggleChatSearch,
}: WorkspaceKeyboardOpts): void {
	useEffect(() => {
		const handleKeyShortcut = (e: KeyboardEvent) => {
			if ((e.metaKey || e.ctrlKey) && e.key === "f") {
				e.preventDefault();
				onToggleChatSearch();
				return;
			}

			// Shift+Tab to toggle Plan Mode
			if (e.shiftKey && e.key === "Tab") {
				e.preventDefault();
				// Use dynamic import to avoid stale closure
				const store = useAgentV3Store.getState();
				const convId = store.activeConversationId;
				if (!convId) return;
				const newMode = store.isPlanMode ? "build" : "plan";
				void import("@/services/planService").then(({ planService }) => {
					planService
						.switchMode(convId, newMode)
						.then(() => {
							useAgentV3Store.getState().updateConversationState(convId, {
								isPlanMode: newMode === "plan",
							});
							useAgentV3Store.setState({ isPlanMode: newMode === "plan" });
						})
						.catch(console.error);
				});
				return;
			}

			// / to focus input (when not already in an input)
			if (e.key === "/" && !e.metaKey && !e.ctrlKey && !e.altKey) {
				const target = e.target as HTMLElement;
				const isInput =
					target.tagName === "INPUT" ||
					target.tagName === "TEXTAREA" ||
					target.isContentEditable;
				if (!isInput) {
					e.preventDefault();
					inputBarRef.current?.focus();
				}
			}
		};
		window.addEventListener("keydown", handleKeyShortcut);
		return () => {
			window.removeEventListener("keydown", handleKeyShortcut);
		};
	}, [inputBarRef, onToggleChatSearch]);
}
