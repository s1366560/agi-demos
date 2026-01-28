import React, { useState, useEffect, useCallback } from 'react';
import { X, Link as LinkIcon, Copy, Trash2, Calendar, Shield, Loader2, Check } from 'lucide-react';
import { Memory } from '../types/memory';
import { memoryAPI } from '../services/api';

interface ShareLink {
    id: string;
    share_token: string;
    permissions: {
        view: boolean;
        edit: boolean;
    };
    expires_at: string | null;
    created_at: string;
    access_count: number;
}

interface ShareLinkResponse {
    id: string;
    share_token: string;
    permissions: {
        view: boolean;
        edit: boolean;
    };
    expires_at: string | null;
    created_at: string;
    access_count: number;
}

interface ShareMemoryModalProps {
    isOpen: boolean;
    onClose: () => void;
    memory: Memory | null;
}

export const ShareMemoryModal: React.FC<ShareMemoryModalProps> = ({
    isOpen,
    onClose,
    memory
}) => {
    const [shares, setShares] = useState<ShareLink[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [isCreating, setIsCreating] = useState(false);
    const [copiedToken, setCopiedToken] = useState<string | null>(null);
    const [viewPermission, setViewPermission] = useState(true);
    const [editPermission, setEditPermission] = useState(false);
    const [expiresIn, setExpiresIn] = useState<number>(7); // days

    const loadShares = useCallback(async () => {
        if (!memory) return;

        setIsLoading(true);
        try {
            const sharesData = await memoryAPI.listShares(memory.id);
            setShares(sharesData as ShareLink[]);
        } catch (error) {
            console.error('Failed to load shares:', error);
            setShares([]);
        } finally {
            setIsLoading(false);
        }
    }, [memory]);

    // Load existing shares when modal opens
    useEffect(() => {
        if (isOpen && memory) {
            loadShares();
        }
    }, [isOpen, memory, loadShares]);

    const handleCreateShare = async () => {
        if (!memory) return;

        setIsCreating(true);
        try {
            // Calculate expiration date
            const expiresAt = expiresIn > 0
                ? new Date(Date.now() + expiresIn * 24 * 60 * 60 * 1000).toISOString()
                : undefined;

            const response = await memoryAPI.createShare(
                memory.id,
                { view: viewPermission, edit: editPermission },
                expiresAt
            );

            // Transform API response to match ShareLink interface
            const newShare: ShareLink = {
                id: (response as ShareLinkResponse).id,
                share_token: (response as ShareLinkResponse).share_token,
                permissions: (response as ShareLinkResponse).permissions,
                expires_at: (response as ShareLinkResponse).expires_at,
                created_at: (response as ShareLinkResponse).created_at,
                access_count: (response as ShareLinkResponse).access_count
            };

            setShares([...shares, newShare]);

            // Reset form
            setViewPermission(true);
            setEditPermission(false);
            setExpiresIn(7);
        } catch (error) {
            console.error('Failed to create share:', error);
            alert('Failed to create share link. Please try again.');
        } finally {
            setIsCreating(false);
        }
    };

    const handleDeleteShare = async (shareId: string) => {
        if (!memory) return;

        if (!window.confirm('确定要删除这个分享链接吗？')) {
            return;
        }

        try {
            await memoryAPI.deleteShare(memory.id, shareId);
            setShares(shares.filter(s => s.id !== shareId));
        } catch (error) {
            console.error('Failed to delete share:', error);
            alert('Failed to delete share link. Please try again.');
        }
    };

    const handleCopyLink = (token: string) => {
        const shareUrl = `${window.location.origin}/shared/${token}`;
        navigator.clipboard.writeText(shareUrl).then(() => {
            setCopiedToken(token);
            setTimeout(() => setCopiedToken(null), 2000);
        });
    };

    const getExpirationText = (expiresAt: string | null) => {
        if (!expiresAt) return '永不过期';
        const expiryDate = new Date(expiresAt);
        const now = new Date();
        const daysLeft = Math.ceil((expiryDate.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
        if (daysLeft <= 0) return '已过期';
        if (daysLeft === 1) return '1天后过期';
        return `${daysLeft}天后过期`;
    };

    if (!isOpen || !memory) return null;

    return (
        <div className="fixed inset-0 bg-black bg-opacity-50 backdrop-blur-sm flex items-center justify-center z-50">
            <div className="bg-white dark:bg-slate-900 rounded-lg shadow-xl w-full max-w-2xl mx-4 max-h-[90vh] overflow-hidden flex flex-col">
                {/* Header */}
                <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-slate-800">
                    <div className="flex items-center space-x-2">
                        <LinkIcon className="h-5 w-5 text-green-600 dark:text-green-400" />
                        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">分享记忆</h2>
                    </div>
                    <button
                        onClick={onClose}
                        className="p-1 text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 rounded-md transition-colors"
                    >
                        <X className="h-5 w-5" />
                    </button>
                </div>

                {/* Content */}
                <div className="flex-1 overflow-y-auto p-6 space-y-6">
                    {/* Create New Share */}
                    <div className="bg-gray-50 dark:bg-slate-800 rounded-lg p-4 space-y-4">
                        <h3 className="font-medium text-gray-900 dark:text-white">创建新分享链接</h3>

                        <div>
                            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-2">
                                权限设置
                            </label>
                            <div className="space-y-2">
                                <label className="flex items-center space-x-2">
                                    <input
                                        type="checkbox"
                                        checked={viewPermission}
                                        onChange={(e) => setViewPermission(e.target.checked)}
                                        className="rounded border-gray-300 dark:border-slate-600"
                                    />
                                    <span className="text-sm text-gray-700 dark:text-slate-300">允许查看</span>
                                </label>
                                <label className="flex items-center space-x-2">
                                    <input
                                        type="checkbox"
                                        checked={editPermission}
                                        onChange={(e) => setEditPermission(e.target.checked)}
                                        className="rounded border-gray-300 dark:border-slate-600"
                                    />
                                    <span className="text-sm text-gray-700 dark:text-slate-300">允许编辑</span>
                                </label>
                            </div>
                        </div>

                        <div>
                            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-2">
                                有效期
                            </label>
                            <select
                                value={expiresIn}
                                onChange={(e) => setExpiresIn(Number(e.target.value))}
                                className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-slate-700 text-gray-900 dark:text-white"
                            >
                                <option value={1}>1天</option>
                                <option value={7}>7天</option>
                                <option value={30}>30天</option>
                                <option value={-1}>永不过期</option>
                            </select>
                        </div>

                        <button
                            onClick={handleCreateShare}
                            disabled={isCreating || !viewPermission && !editPermission}
                            className="w-full px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                        >
                            {isCreating && <Loader2 className="h-4 w-4 animate-spin" />}
                            {isCreating ? '创建中...' : '创建分享链接'}
                        </button>
                    </div>

                    {/* Existing Shares */}
                    <div>
                        <h3 className="font-medium text-gray-900 dark:text-white mb-3">活跃的分享链接</h3>

                        {isLoading ? (
                            <div className="flex items-center justify-center py-8">
                                <Loader2 className="h-8 w-8 animate-spin text-blue-600 dark:text-blue-400" />
                            </div>
                        ) : shares.length === 0 ? (
                            <div className="text-center py-8 text-gray-500 dark:text-slate-400">
                                <LinkIcon className="h-12 w-12 mx-auto mb-2 opacity-50" />
                                <p>暂无分享链接</p>
                            </div>
                        ) : (
                            <div className="space-y-3">
                                {shares.map((share) => (
                                    <div
                                        key={share.id}
                                        className="bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg p-4"
                                    >
                                        <div className="flex items-start justify-between mb-3">
                                            <div className="flex-1">
                                                <div className="flex items-center gap-2 mb-2">
                                                    <LinkIcon className="h-4 w-4 text-green-600 dark:text-green-400" />
                                                    <code className="text-sm font-mono bg-gray-100 dark:bg-slate-900 px-2 py-1 rounded">
                                                        /shared/{share.share_token}
                                                    </code>
                                                </div>
                                                <div className="flex items-center gap-4 text-xs text-gray-500 dark:text-slate-400">
                                                    <div className="flex items-center gap-1">
                                                        <Calendar className="h-3 w-3" />
                                                        <span>{getExpirationText(share.expires_at)}</span>
                                                    </div>
                                                    <div className="flex items-center gap-1">
                                                        <Shield className="h-3 w-3" />
                                                        <span>
                                                            {share.permissions.view && '查看'}
                                                            {share.permissions.view && share.permissions.edit && ' + '}
                                                            {share.permissions.edit && '编辑'}
                                                        </span>
                                                    </div>
                                                    <div>访问 {share.access_count} 次</div>
                                                </div>
                                            </div>
                                            <div className="flex items-center gap-2">
                                                <button
                                                    onClick={() => handleCopyLink(share.share_token)}
                                                    className="p-2 text-gray-400 hover:text-blue-600 dark:hover:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded-md transition-colors"
                                                    title="复制链接"
                                                >
                                                    {copiedToken === share.share_token ? (
                                                        <Check className="h-4 w-4 text-green-600" />
                                                    ) : (
                                                        <Copy className="h-4 w-4" />
                                                    )}
                                                </button>
                                                <button
                                                    onClick={() => handleDeleteShare(share.id)}
                                                    className="p-2 text-gray-400 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-md transition-colors"
                                                    title="删除链接"
                                                >
                                                    <Trash2 className="h-4 w-4" />
                                                </button>
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};
