import { memo } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertCircle,
  File,
  FileText,
  Image as ImageIcon,
  RotateCw,
  X,
} from "lucide-react";
import { Tooltip as LazyTooltip } from "antd";
import { formatFileSize } from "../../../../../../sdk/memstack-plugin-sdk/ui/formatFileSize";
const getFileIcon = (mimeType: string) => {
  if (mimeType.startsWith("image/"))
    return <ImageIcon size={14} className="text-emerald-500" />;
  if (mimeType.includes("pdf") || mimeType.includes("document"))
    return <FileText size={14} className="text-red-500" />;
  return <File size={14} className="text-blue-500" />;
};

export const AttachmentChip = memo<{
  file: {
    id: string;
    filename: string;
    mimeType: string;
    sizeBytes: number;
    status: string;
    progress: number;
    error?: string | undefined;
  };
  onRemove: (id: string) => void;
  onRetry: (id: string) => void;
}>(({ file, onRemove, onRetry }) => {
  const { t } = useTranslation();
  const retryLabel = t("agent.inputBar.retryAttachmentUpload", {
    filename: file.filename,
    defaultValue: "Retry upload for {{filename}}",
  });
  const removeLabel = t("agent.inputBar.removeAttachment", {
    filename: file.filename,
    defaultValue: "Remove {{filename}} attachment",
  });

  return (
    <div
      className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs border transition-colors ${
        file.status === "error"
          ? "bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800/50"
          : "bg-slate-50 dark:bg-slate-700/50 border-slate-200 dark:border-slate-600"
      }`}
    >
      {getFileIcon(file.mimeType)}
      <span className="max-w-[120px] truncate text-slate-700 dark:text-slate-300">
        {file.filename}
      </span>
      <span className="text-slate-400">{formatFileSize(file.sizeBytes)}</span>
      {file.status === "uploading" && (
        <span className="text-blue-500 font-medium">{file.progress}%</span>
      )}
      {file.status === "error" && (
        <>
          <LazyTooltip title={file.error}>
            <AlertCircle size={13} className="text-red-500 cursor-help" />
          </LazyTooltip>
          <button
            type="button"
            onClick={() => {
              onRetry(file.id);
            }}
            aria-label={retryLabel}
            title={retryLabel}
            className="p-0.5 hover:bg-red-100 dark:hover:bg-red-900/30 rounded-md transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
          >
            <RotateCw size={12} className="text-red-500" />
          </button>
        </>
      )}
      <button
        type="button"
        onClick={() => {
          onRemove(file.id);
        }}
        disabled={file.status === "uploading"}
        aria-label={removeLabel}
        title={removeLabel}
        className="p-0.5 hover:bg-slate-200 dark:hover:bg-slate-600 rounded-md transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 ml-0.5 disabled:opacity-30"
      >
        <X size={12} className="text-slate-400 hover:text-slate-600" />
      </button>
    </div>
  );
});

AttachmentChip.displayName = "AttachmentChip";
