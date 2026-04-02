import * as React from "react";
import { useState } from "react";
import { Download, ChevronDown, GitCompareArrows } from "lucide-react";
import { LayoutModeSelector } from "./layout/LayoutModeSelector";
import { useTranslation } from "react-i18next";
import type { TimelineEvent } from "@/types/agent";

export interface WorkspaceStatusBarProps {
	statusBar: React.ReactNode;
	activeConversationId: string | null;
	timeline: TimelineEvent[];
	onCompare: () => void;
	onExportMarkdown: () => void;
	onExportPdf: () => void;
}

export const WorkspaceStatusBar: React.FC<WorkspaceStatusBarProps> = ({
	statusBar,
	activeConversationId,
	timeline,
	onCompare,
	onExportMarkdown,
	onExportPdf,
}) => {
	const { t } = useTranslation();
	const [showExportMenu, setShowExportMenu] = useState(false);

	return (
		<div className="flex-shrink-0 flex items-center border-t border-slate-200/60 dark:border-slate-700/50 bg-slate-50 dark:bg-slate-800/80 min-w-0">
			<div className="flex-1 min-w-0 overflow-hidden">{statusBar}</div>
			<div className="flex items-center gap-1 sm:gap-2 pr-2 sm:pr-3 flex-shrink-0">
				{activeConversationId && timeline.length > 0 && (
					<button
						type="button"
						onClick={onCompare}
						className="flex items-center gap-1 p-1.5 rounded-md text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
						title={t("comparison.compare", "Compare")}
						aria-label={t("comparison.compare", "Compare")}
					>
						<GitCompareArrows size={14} />
					</button>
				)}
				{timeline.length > 0 && (
					<div className="relative">
						<button
							type="button"
							onClick={() => {
								setShowExportMenu((v) => !v);
							}}
							onBlur={() => {
								setTimeout(() => {
									setShowExportMenu(false);
								}, 150);
							}}
							className="flex items-center gap-0.5 p-1.5 rounded-md text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
							title={t("agent.actions.export", "Export")}
							aria-label={t("agent.actions.export", "Export")}
						>
							<Download size={14} />
							<ChevronDown size={10} />
						</button>
						{showExportMenu && (
							<div className="absolute bottom-full right-0 mb-1 w-48 rounded-md border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 shadow-lg z-50 py-1">
								<button
									type="button"
									onMouseDown={(e) => {
										e.preventDefault();
										onExportMarkdown();
										setShowExportMenu(false);
									}}
									className="w-full text-left px-3 py-1.5 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700"
								>
									{t("agent.actions.exportMarkdown", "Export as Markdown")}
								</button>
								<button
									type="button"
									onMouseDown={(e) => {
										e.preventDefault();
										onExportPdf();
										setShowExportMenu(false);
									}}
									className="w-full text-left px-3 py-1.5 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700"
								>
									{t("agent.actions.exportPdf", "Export as PDF")}
								</button>
							</div>
						)}
					</div>
				)}
				<LayoutModeSelector />
			</div>
		</div>
	);
};
