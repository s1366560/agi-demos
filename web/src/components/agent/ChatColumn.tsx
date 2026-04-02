import * as React from "react";
import { Bot, GripHorizontal } from "lucide-react";
import { Resizer } from "./Resizer";
import { SubAgentMiniMap } from "./timeline/SubAgentMiniMap";
import { ChatSearch } from "./chat/ChatSearch";
import { InputBar } from "./index";
import type { SubAgentSummary } from "./message/groupTimelineEvents";
import type { TimelineEvent } from "@/types/agent";
import type { FileMetadata } from "@/services/sandboxUploadService";

export const INPUT_MIN_HEIGHT = 140;
export const INPUT_MAX_HEIGHT = 560;
export const INPUT_DEFAULT_HEIGHT = 180;

export interface ChatColumnProps {
	headerExtra?: React.ReactNode;
	activeAgentNode: { name: string | null; status: string } | null;
	messageArea: React.ReactNode;
	subagentSummaries: SubAgentSummary[];
	onScrollToSubAgent: (startIndex: number) => void;
	timeline: TimelineEvent[];
	chatSearchVisible: boolean;
	onChatSearchClose: () => void;
	inputHeight: number;
	onInputHeightChange: (h: number) => void;
	inputBarRef: React.RefObject<HTMLTextAreaElement | null>;
	onSend: (
		content: string,
		fileMetadata?: FileMetadata[],
		forcedSkillName?: string,
		forcedSubAgentName?: string,
		imageAttachments?: string[],
	) => void;
	onAbort: () => void;
	isStreaming: boolean;
	isLoadingHistory: boolean;
	projectId?: string | undefined;
	onTogglePlanMode: () => void;
	isPlanMode: boolean;
	activeAgentId?: string | undefined;
	onAgentSelect: (id: string | undefined) => void;
}

export const ChatColumn: React.FC<ChatColumnProps> = ({
	headerExtra,
	activeAgentNode,
	messageArea,
	subagentSummaries,
	onScrollToSubAgent,
	timeline,
	chatSearchVisible,
	onChatSearchClose,
	inputHeight,
	onInputHeightChange,
	inputBarRef,
	onSend,
	onAbort,
	isStreaming,
	isLoadingHistory,
	projectId,
	onTogglePlanMode,
	isPlanMode,
	activeAgentId,
	onAgentSelect,
}) => {
	return (
		<div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden relative">
			{headerExtra && (
				<div className="flex-shrink-0 border-b border-slate-200/60 dark:border-slate-700/50 bg-white dark:bg-slate-900 px-4 py-2 flex items-center gap-2">
					{headerExtra}
				</div>
			)}
			{activeAgentNode?.name && (
				<div className="flex-shrink-0 border-b border-slate-200/60 dark:border-slate-700/50 bg-blue-50/50 dark:bg-blue-900/20 px-4 py-1.5 flex items-center gap-2">
					<span className="flex items-center gap-1.5 bg-blue-100 dark:bg-blue-900/50 text-blue-700 dark:text-blue-300 text-xs font-medium px-2 py-0.5 rounded-full">
						<Bot size={12} />
						{activeAgentNode.name}
					</span>
				</div>
			)}
			<div className="flex-1 overflow-hidden relative min-h-0">
				{messageArea}
				{subagentSummaries.length >= 3 && (
					<SubAgentMiniMap
						summaries={subagentSummaries}
						onScrollTo={onScrollToSubAgent}
					/>
				)}
				<ChatSearch
					timeline={timeline}
					visible={chatSearchVisible}
					onClose={onChatSearchClose}
				/>
			</div>
			<div
				className="flex-shrink-0 border-t border-slate-200/60 dark:border-slate-700/50 bg-white dark:bg-slate-900 relative flex flex-col shadow-[0_-4px_20px_rgba(0,0,0,0.03)]"
				style={{ height: inputHeight }}
			>
				<div className="absolute -top-2 left-0 right-0 z-40 flex justify-center">
					<Resizer
						direction="vertical"
						currentSize={inputHeight}
						minSize={INPUT_MIN_HEIGHT}
						maxSize={INPUT_MAX_HEIGHT}
						onResize={onInputHeightChange}
						position="top"
					/>
					<div className="pointer-events-none absolute top-1 flex items-center gap-1 text-slate-400">
						<GripHorizontal size={12} />
					</div>
				</div>
				<InputBar
					ref={inputBarRef}
					onSend={(...args) => {
						onSend(...args);
					}}
					onAbort={onAbort}
					isStreaming={isStreaming}
					disabled={isLoadingHistory}
					projectId={projectId}
					onTogglePlanMode={() => {
						onTogglePlanMode();
					}}
					isPlanMode={isPlanMode}
					activeAgentId={activeAgentId}
					onAgentSelect={onAgentSelect}
				/>
			</div>
		</div>
	);
};
