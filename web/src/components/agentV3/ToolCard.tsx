import React from "react";
import { Card, Tag, Collapse, Typography } from "antd";
import { CheckCircleOutlined, SyncOutlined, CloseCircleOutlined, ClockCircleOutlined } from "@ant-design/icons";

const { Panel } = Collapse;
const { Text } = Typography;

interface ToolCardProps {
    toolName: string;
    input: Record<string, unknown>;
    result?: string;
    status: "running" | "success" | "failed";
    startTime?: number;
    endTime?: number;
    duration?: number;
    embedded?: boolean; // When true, use compact styling for timeline embedding
}

export const ToolCard: React.FC<ToolCardProps> = ({
    toolName,
    input,
    result,
    status,
    startTime,
    endTime,
    duration,
    embedded = false,
}) => {
    const getIcon = () => {
        switch (status) {
            case "running":
                return <SyncOutlined spin className="text-blue-500" />;
            case "success":
                return <CheckCircleOutlined className="text-green-500" />;
            case "failed":
                return <CloseCircleOutlined className="text-red-500" />;
        }
    };

    const formatDuration = (ms: number) => {
        if (ms < 1000) return `${ms}ms`;
        return `${(ms / 1000).toFixed(2)}s`;
    };

    const getHeader = () => (
        <div className="flex items-center gap-2 w-full">
            {getIcon()}
            <span className="font-semibold text-sm">{toolName}</span>
            <div className="ml-auto flex items-center gap-2">
                {duration && (
                    <Tag icon={<ClockCircleOutlined />} className="mr-0 text-xs">
                        {formatDuration(duration)}
                    </Tag>
                )}
                <Tag className="mr-0 text-xs" color={status === 'success' ? 'success' : status === 'failed' ? 'error' : 'processing'}>
                    {status.toUpperCase()}
                </Tag>
            </div>
        </div>
    );

    const content = (
        <Collapse ghost size="small" defaultActiveKey={status === 'running' ? ['1'] : []}>
            <Panel header={getHeader()} key="1">
                <div className="space-y-2">
                    {/* Timing Info */}
                    {(startTime || endTime) && !embedded && (
                        <div className="flex gap-4 text-xs text-slate-400 mb-2 border-b border-slate-100 pb-2">
                            {startTime && <span>Start: {new Date(startTime).toLocaleTimeString()}</span>}
                            {endTime && <span>End: {new Date(endTime).toLocaleTimeString()}</span>}
                        </div>
                    )}

                    <div>
                        <Text type="secondary" className="text-xs uppercase font-bold">Input</Text>
                        <pre className={`p-2 rounded text-xs border overflow-x-auto max-w-full whitespace-pre-wrap break-all ${
                            embedded ? 'bg-white/80 border-slate-200' : 'bg-white border-slate-100'
                        }`}>
                            {JSON.stringify(input, null, 2)}
                        </pre>
                    </div>
                    {result && (
                        <div>
                            <Text type="secondary" className="text-xs uppercase font-bold">Result</Text>
                            <pre className={`p-2 rounded text-xs border overflow-x-auto max-w-full whitespace-pre-wrap break-all ${
                                embedded ? 'bg-white/80 border-slate-200 max-h-40' : 'bg-white border-slate-100 max-h-60'
                            }`}>
                                {result}
                            </pre>
                        </div>
                    )}
                </div>
            </Panel>
        </Collapse>
    );

    // When embedded, skip the Card wrapper (parent TimelineNode provides styling)
    if (embedded) {
        return content;
    }

    return (
        <Card size="small" className="mb-2 border-slate-200 shadow-sm bg-slate-50">
            {content}
        </Card>
    );
};
