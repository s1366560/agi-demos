import type { FC, KeyboardEvent, MouseEvent, ReactNode } from "react";

import { LAYOUT_BG_CLASSES } from "./styles";

export interface SplitPaneLayoutProps {
	leftContent: ReactNode;
	rightContent: ReactNode;
	splitRatio: number;
	onSplitDrag: (e: MouseEvent) => void;
	onSplitKeyDown: (e: KeyboardEvent) => void;
	/** Accent color for the drag handle hover state */
	handleAccentColor?: "purple" | "primary" | "violet";
	/** Optional min-width for left pane */
	leftMinWidth?: string;
	/** Optional min-width for right pane */
	rightMinWidth?: string;
	/** Optional extra className for the right pane */
	rightClassName?: string;
	className?: string;
	statusBar: ReactNode;
}

export const SplitPaneLayout: FC<SplitPaneLayoutProps> = ({
	leftContent,
	rightContent,
	splitRatio,
	onSplitDrag,
	onSplitKeyDown,
	handleAccentColor = "purple",
	leftMinWidth,
	rightMinWidth,
	rightClassName = "",
	className = "",
	statusBar,
}) => {
	const leftPercent = `${String(splitRatio * 100)}%`;
	const rightPercent = `${String((1 - splitRatio) * 100)}%`;

	const handleBgHover = {
		purple: "hover:bg-purple-500/20 active:bg-purple-500/30",
		primary: "hover:bg-primary-500/20 active:bg-primary-500/30",
		violet: "hover:bg-violet-500/20 active:bg-violet-500/30",
	}[handleAccentColor];

	const handleIndicatorHover = {
		purple: "group-hover:bg-purple-500/70",
		primary: "group-hover:bg-primary-500/70",
		violet: "group-hover:bg-violet-500/70",
	}[handleAccentColor];

	return (
		<div
			className={`flex flex-col h-full w-full overflow-hidden ${LAYOUT_BG_CLASSES} ${className}`}
		>
			<div className="flex-1 flex min-h-0 overflow-hidden mobile-stack">
				{/* Left: Chat */}
				<div
					className="h-full overflow-hidden flex flex-col mobile-full"
					style={{ width: leftPercent, minWidth: leftMinWidth }}
				>
					{leftContent}
				</div>

				{/* Drag handle */}
				<div
					className={`flex-shrink-0 w-1.5 h-full cursor-col-resize relative group transition-colors z-10 mobile-hidden ${handleBgHover}`}
					role="slider"
					aria-valuenow={Math.round(splitRatio * 100)}
					aria-valuemin={20}
					aria-valuemax={80}
					tabIndex={0}
					aria-label="Resize panels"
					onKeyDown={onSplitKeyDown}
					onMouseDown={onSplitDrag}
				>
					<div
						className={`absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-0.5 h-8 rounded-full bg-border-light/50 transition-colors ${handleIndicatorHover}`}
					/>
				</div>

				{/* Right Panel */}
				<div
					className={`h-full overflow-hidden border-l border-border-light/60 dark:border-border-dark/50 mobile-full ${rightClassName}`}
					style={{ width: rightPercent, minWidth: rightMinWidth }}
				>
					{rightContent}
				</div>
			</div>

			{statusBar}
		</div>
	);
};
