/**
 * ToolExecutionCard component (T054)
 *
 * Displays tool execution information including
 * the tool name, input parameters, execution status, and results.
 *
 * PERFORMANCE: Wrapped with React.memo to prevent unnecessary re-renders.
 */

import { useState, memo } from "react";

import {
  ToolOutlined,
  LoadingOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  CaretDownOutlined,
  CaretRightOutlined,
  PictureOutlined,
} from "@ant-design/icons";
import { Card, Typography, Space, Tag, Image as AntImage } from "antd";

import {
  isImageUrl as _isImageUrl,
  parseBase64Image,
  extractImageUrl,
  foldText,
} from "../../utils/toolResultUtils";

import {
  CodeExecutorResultCard,
  parseCodeExecutorResult,
} from "./CodeExecutorResultCard";
import { WebScrapeResultCard } from "./WebScrapeResultCard";
import { WebSearchResultCard, type SearchResult } from "./WebSearchResultCard";


const { Text, Link } = Typography;

// Parse web search results from formatted string
function parseWebSearchResults(result: string): {
  query: string;
  totalResults: number;
  cached: boolean;
  results: SearchResult[];
} | null {
  try {
    const lines = result.split("\n");
    const results: SearchResult[] = [];
    let query = "";
    let totalResults = 0;
    let cached = false;

    // Parse header
    const headerMatch = lines[0]?.match(/Found (\d+) result\(s\) for '(.+?)'/);
    if (headerMatch) {
      totalResults = parseInt(headerMatch[1], 10);
      query = headerMatch[2];
      cached = lines[0]?.includes("(cached)") || false;
    }

    // Parse results
    let currentResult: Partial<SearchResult> | null = null;
    for (const line of lines.slice(1)) {
      const trimmed = line.trim();
      // Match result number: "1. Title"
      const titleMatch = trimmed.match(/^\d+\.\s+(.+)$/);
      if (titleMatch) {
        if (currentResult?.title && currentResult.url) {
          results.push(currentResult as SearchResult);
        }
        currentResult = {
          title: titleMatch[1],
          url: "",
          content: "",
          score: 0,
        };
      } else if (trimmed.startsWith("URL:") && currentResult) {
        currentResult.url = trimmed.replace("URL:", "").trim();
      } else if (trimmed.startsWith("Score:") && currentResult) {
        currentResult.score = parseFloat(trimmed.replace("Score:", "").trim());
      } else if (trimmed.startsWith("Content:") && currentResult) {
        currentResult.content = trimmed.replace("Content:", "").trim();
      }
    }
    if (currentResult?.title && currentResult.url) {
      results.push(currentResult as SearchResult);
    }

    if (results.length > 0) {
      return { query, totalResults, cached, results };
    }
  } catch {
    // Fall through to null
  }
  return null;
}

// Parse web scrape results from formatted string
function parseWebScrapeResults(result: string): {
  title: string;
  url: string;
  description: string;
  content: string;
} | null {
  try {
    const lines = result.split("\n");
    let title = "";
    let url = "";
    let description = "";
    const contentLines: string[] = [];
    let inContent = false;

    for (const line of lines) {
      if (line.startsWith("Title:")) {
        title = line.replace("Title:", "").trim();
      } else if (line.startsWith("URL:")) {
        url = line.replace("URL:", "").trim();
      } else if (line.startsWith("Description:")) {
        description = line.replace("Description:", "").trim();
      } else if (line.startsWith("Content:")) {
        inContent = true;
      } else if (inContent) {
        contentLines.push(line);
      }
    }

    if (title && url) {
      return { title, url, description, content: contentLines.join("\n") };
    }
  } catch {
    // Fall through to null
  }
  return null;
}

interface ToolExecutionCardProps {
  toolCall: {
    name: string;
    input: Record<string, unknown>;
    result?: string;
    error?: string;
    stepNumber?: number;
    duration?: number;
    timestamp?: string;
  };
}

const formatJson = (obj: Record<string, unknown>): string => {
  try {
    return JSON.stringify(obj, null, 2);
  } catch {
    return String(obj);
  }
};

const formatDuration = (ms: number): string => {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
};

export const ToolExecutionCard = memo<ToolExecutionCardProps>(({ toolCall }) => {
  const [collapsed, setCollapsed] = useState(false);
  const hasResult = toolCall.result !== undefined;
  const hasError = toolCall.error !== undefined;
  const isRunning = !hasResult && !hasError;

  const status = hasError ? "failed" : isRunning ? "running" : "completed";
  const statusConfig = {
    running: {
      icon: <LoadingOutlined />,
      label: "Executing",
      class: "status-running",
    },
    completed: {
      icon: <CheckCircleOutlined />,
      label: "Completed",
      class: "status-completed",
    },
    failed: {
      icon: <CloseCircleOutlined />,
      label: "Failed",
      class: "status-failed",
    },
  };
  const config = statusConfig[status];

  // Format timestamp
  const timeDisplay = toolCall.timestamp
    ? new Date(toolCall.timestamp).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      })
    : undefined;

  // Convert tool name to class-friendly format (replace underscores with hyphens)
  const toolClassName = toolCall.name.replace(/_/g, "-");

  // Parse structured results
  const isWebSearch = toolCall.name === "web_search";
  const isWebScrape = toolCall.name === "web_scrape";
  const isCodeExecutor = toolCall.name === "code_executor";
  const webSearchResults =
    isWebSearch && hasResult && toolCall.result
      ? parseWebSearchResults(toolCall.result)
      : null;
  const webScrapeResults =
    isWebScrape && hasResult && toolCall.result
      ? parseWebScrapeResults(toolCall.result)
      : null;
  const codeExecutorResults =
    isCodeExecutor && hasResult && toolCall.result
      ? parseCodeExecutorResult(toolCall.result)
      : null;

  // Parse image results
  const imageUrl =
    hasResult && toolCall.result ? extractImageUrl(toolCall.result) : null;
  const base64Image =
    hasResult && toolCall.result ? parseBase64Image(toolCall.result) : null;
  const hasImageResult = imageUrl !== null || base64Image !== null;

  const hasStructuredResults =
    webSearchResults !== null ||
    webScrapeResults !== null ||
    codeExecutorResults !== null ||
    hasImageResult;

  return (
    <Card
      data-testid="tool-execution-card"
      size="small"
      className={`tool-execution-card tool-${toolClassName} ${config.class}`}
      style={{
        marginBottom: 8,
        backgroundColor:
          status === "completed"
            ? "#f6ffed"
            : status === "failed"
            ? "#fff1f0"
            : "#e6f7ff",
        border: `1px solid ${
          status === "completed"
            ? "#b7eb8f"
            : status === "failed"
            ? "#ffccc7"
            : "#91d5ff"
        }`,
      }}
      aria-label={`Tool execution: ${toolCall.name}`}
    >
      <Space orientation="vertical" size="small" style={{ width: "100%" }}>
        {/* Header */}
        <Space style={{ width: "100%", justifyContent: "space-between" }}>
          <Space>
            <ToolOutlined />
            <Text strong>{toolCall.name}</Text>
            {toolCall.stepNumber !== undefined && (
              <Tag color="blue">Step {toolCall.stepNumber + 1}</Tag>
            )}
            <Tag
              icon={config.icon}
              color={
                status === "completed"
                  ? "success"
                  : status === "failed"
                  ? "error"
                  : "processing"
              }
              data-testid="tool-status-indicator"
              aria-live="polite"
            >
              {config.label}
            </Tag>
          </Space>

          {(toolCall.result ||
            hasError ||
            Object.keys(toolCall.input).length > 0) && (
            <Typography.Link
              onClick={() => setCollapsed(!collapsed)}
              style={{ fontSize: 11 }}
              aria-label={collapsed ? "Show details" : "Hide details"}
            >
              {collapsed ? <CaretRightOutlined /> : <CaretDownOutlined />}
            </Typography.Link>
          )}
        </Space>

        {/* Metadata */}
        <Space wrap>
          {toolCall.duration && (
            <Text type="secondary" style={{ fontSize: 11 }}>
              Duration: {formatDuration(toolCall.duration)}
            </Text>
          )}
          {timeDisplay && (
            <Text type="secondary" style={{ fontSize: 11 }}>
              {timeDisplay}
            </Text>
          )}
        </Space>

        {/* Collapsible Details */}
        {!collapsed && (
          <Space orientation="vertical" size="small" style={{ width: "100%" }}>
            {/* Input Parameters */}
            {Object.keys(toolCall.input).length > 0 ? (
              <div>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  Input:
                </Text>
                <pre
                  className="json-syntax-highlight"
                  style={{
                    backgroundColor: "#f5f5f5",
                    padding: 8,
                    borderRadius: 4,
                    fontSize: 11,
                    marginTop: 4,
                    overflow: "auto",
                    maxHeight: 150,
                    border: "1px solid #d9d9d9",
                  }}
                >
                  {formatJson(toolCall.input)}
                </pre>
              </div>
            ) : (
              <Text type="secondary" style={{ fontSize: 11 }}>
                No parameters
              </Text>
            )}

            {/* Result */}
            {hasError ? (
              <div className="tool-error error-text">
                <Text type="danger" style={{ fontSize: 11 }}>
                  Error: {toolCall.error}
                </Text>
              </div>
            ) : hasStructuredResults ? (
              <>
                {/* Structured Results for web_search and web_scrape */}
                {webSearchResults && (
                  <WebSearchResultCard
                    query={webSearchResults.query}
                    totalResults={webSearchResults.totalResults}
                    cached={webSearchResults.cached}
                    results={webSearchResults.results}
                  />
                )}
                {webScrapeResults && (
                  <WebScrapeResultCard
                    title={webScrapeResults.title}
                    url={webScrapeResults.url}
                    description={webScrapeResults.description}
                    content={webScrapeResults.content}
                  />
                )}
                {codeExecutorResults && (
                  <CodeExecutorResultCard result={codeExecutorResults} />
                )}
                {/* Image Results - URL or Base64 */}
                {hasImageResult && (
                  <div data-testid="tool-image-result">
                    <Text
                      type="secondary"
                      style={{
                        fontSize: 11,
                        marginBottom: 8,
                        display: "block",
                      }}
                    >
                      <PictureOutlined style={{ marginRight: 4 }} />
                      Image Result:
                    </Text>
                    <div
                      style={{
                        backgroundColor: "#fafafa",
                        padding: 12,
                        borderRadius: 8,
                        border: "1px solid #d9d9d9",
                        textAlign: "center",
                      }}
                    >
                      {imageUrl ? (
                        <>
                          <AntImage
                            src={imageUrl}
                            alt="Tool result image"
                            style={{
                              maxWidth: "100%",
                              maxHeight: 400,
                              borderRadius: 4,
                            }}
                            placeholder={
                              <div
                                style={{
                                  width: 200,
                                  height: 150,
                                  display: "flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  backgroundColor: "#f5f5f5",
                                }}
                              >
                                <LoadingOutlined style={{ fontSize: 24 }} />
                              </div>
                            }
                          />
                          <div style={{ marginTop: 8 }}>
                            <Link
                              href={imageUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              style={{ fontSize: 11 }}
                            >
                              Open in new tab
                            </Link>
                          </div>
                        </>
                      ) : base64Image ? (
                        <AntImage
                          src={`data:image/${base64Image.format};base64,${base64Image.data}`}
                          alt="Tool result screenshot"
                          style={{
                            maxWidth: "100%",
                            maxHeight: 400,
                            borderRadius: 4,
                          }}
                        />
                      ) : null}
                    </div>
                  </div>
                )}
              </>
            ) : hasResult ? (
              <div data-testid="tool-result">
                <Text type="secondary" style={{ fontSize: 11 }}>
                  Result:
                </Text>
                <pre
                  style={{
                    backgroundColor: "#f5f5f5",
                    padding: 8,
                    borderRadius: 4,
                    fontSize: 11,
                    marginTop: 4,
                    overflow: "auto",
                    maxHeight: 200,
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    border: "1px solid #d9d9d9",
                  }}
                >
                  {foldText(toolCall.result, 5) || "(empty)"}
                </pre>
              </div>
            ) : null}
          </Space>
        )}
      </Space>
    </Card>
  );
});

ToolExecutionCard.displayName = 'ToolExecutionCard';

export default ToolExecutionCard;
