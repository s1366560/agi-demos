import type { FC, ReactNode } from "react";
import { useCallback } from "react";

import { LAYOUT_BG_CLASSES } from "./styles";

export interface SplitPaneLayoutProps {
	leftContent: ReactNode;
	rightContent: ReactNode;
	splitRatio: number;
	onSplitRatioChange: (ratio: number) => void;
	minRatio?: number;
	maxRatio?: number;
	/** Accent color for the drag handle hover state */
	handleAccentColor?: "purple" | "primary" | "violet";
	/** Optional min-width for left pane */
	leftMinWidth?: string | undefined;
	/** Optional min-width for right pane */
	rightMinWidth?: string | undefined;
	/** Optional extra className for the right pane */
	rightClassName?: string;
	className?: string;
	statusBar: ReactNode;
}

export const SplitPaneLayout: FC<SplitPaneLayoutProps> = ({
	leftContent,
	rightContent,
	splitRatio,
	onSplitRatioChange,
	minRatio = 0.2,
	maxRatio = 0.8,
	handleAccentColor = "purple",
	leftMinWidth,
	rightMinWidth,
	rightClassName = "",
	className = "",
	statusBar,
}) => {
	const handleSplitDrag = useCallback(
		(e: React.MouseEvent) => {
			e.preventDefault();
			const startX = e.clientX;
			const startRatio = splitRatio;
			const containerWidth =
				(e.currentTarget as HTMLElement).parentElement?.offsetWidth ||
				window.innerWidth;

			let animationFrameId: number | null = null;

			const onMove = (ev: MouseEvent) => {
				if (animationFrameId !== null) {
					cancelAnimationFrame(animationFrameId);
				}
				animationFrameId = requestAnimationFrame(() => {
					const delta = ev.clientX - startX;
					const newRatio = Math.max(
						minRatio,
						Math.min(maxRatio, startRatio + delta / containerWidth),
					);
					onSplitRatioChange(newRatio);
				});
			};
			const onUp = () => {
				if (animationFrameId !== null) {
					cancelAnimationFrame(animationFrameId);
				}
				document.removeEventListener("mousemove", onMove);
				document.removeEventListener("mouseup", onUp);
				document.body.style.cursor = "";
				document.body.style.userSelect = "";
			};
			document.body.style.cursor = "col-resize";
			document.body.style.userSelect = "none";
			document.addEventListener("mousemove", onMove);
			document.addEventListener("mouseup", onUp);
		},
		[splitRatio, onSplitRatioChange, minRatio, maxRatio],
	);

	const handleSplitKeyDown = useCallback(
		(e: React.KeyboardEvent) => {
			const step = e.shiftKey ? 0.05 : 0.02;
			let newRatio = splitRatio;
			if (e.key === "ArrowRight") newRatio = splitRatio + step;
			else if (e.key === "ArrowLeft") newRatio = splitRatio - step;
			else return;
			e.preventDefault();
			onSplitRatioChange(Math.max(minRatio, Math.min(maxRatio, newRatio)));
		},
		[splitRatio, onSplitRatioChange, minRatio, maxRatio],
	);

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
					aria-valuemin={minRatio * 100}
					aria-valuemax={maxRatio * 100}
					tabIndex={0}
					aria-label="Resize panels"
					onKeyDown={handleSplitKeyDown}
					onMouseDown={handleSplitDrag}
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
