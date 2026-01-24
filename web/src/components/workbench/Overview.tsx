import React, { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
    Brain,
    HardDrive,
    Network,
    Users,
    TrendingUp,
    CheckCircle,
    FileText,
    MoreVertical,
    Activity,
    Plus,
    Image as ImageIcon,
    File
} from 'lucide-react';
import { useMemoryStore } from '../../stores/memory';
import { useProjectStore } from '../../stores/project';
import { formatDistanceToNow } from 'date-fns';
import { useParams } from 'react-router-dom';

interface OverviewProps {
    onNavigate: (tab: string) => void;
}

const StatsCard: React.FC<{
    title: string;
    value: string | number;
    icon: React.ElementType;
    trend?: string;
    trendUp?: boolean;
    subtext?: string;
    colorClass: string;
    bgClass: string;
}> = ({ title, value, icon: Icon, trend, trendUp, subtext, colorClass, bgClass }) => (
    <div className="bg-white dark:bg-[#1e2332] p-5 rounded-lg border border-slate-200 dark:border-slate-800 shadow-sm flex flex-col justify-between h-32 hover:border-blue-500/50 transition-colors group">
        <div className="flex justify-between items-start">
            <div className="flex flex-col">
                <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">{title}</span>
                <span className="text-2xl font-bold text-slate-900 dark:text-white mt-1">{value}</span>
            </div>
            <div className={`p-2 rounded-md transition-colors ${bgClass} ${colorClass} group-hover:bg-opacity-80`}>
                <Icon className="h-5 w-5" />
            </div>
        </div>
        {trend && (
            <div className={`flex items-center gap-1 text-xs font-medium ${trendUp ? 'text-green-600' : 'text-slate-500'}`}>
                {trendUp && <TrendingUp className="h-4 w-4" />}
                <span>{trend}</span>
            </div>
        )}
        {subtext && (
             <div className="flex items-center gap-1 text-xs text-slate-500 font-medium">
                {subtext === 'All systems operational' && <CheckCircle className="h-4 w-4 text-green-500" />}
                <span>{subtext}</span>
            </div>
        )}
    </div>
);

export const Overview: React.FC<OverviewProps> = ({ onNavigate }) => {
    const { t: _t } = useTranslation();
    const { spaceId, projectId } = useParams<{ spaceId: string; projectId: string }>();
    
    const { currentProject } = useProjectStore();
    const {
        memories,
        listMemories,
        isLoading: isMemoriesLoading
    } = useMemoryStore();

    useEffect(() => {
        if (spaceId && projectId) {
            listMemories(projectId, { page_size: 5 });
        }
    }, [spaceId, projectId, listMemories]);

    const stats = currentProject?.stats || {
        memory_count: 0,
        storage_used: 0,
        node_count: 0,
        member_count: 0
    };

    // Mock formatting for storage
    const formatStorage = (bytes: number) => {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    };

    // Mock team members
    const teamMembers = [
        { name: 'Sarah Jenkins', status: 'Editing "Quarterly..."', online: true, color: 'bg-green-500' },
        { name: 'Mike Ross', status: 'Idle - 5m ago', online: true, color: 'bg-yellow-500' },
        { name: 'David Chen', status: 'Offline', online: false, color: 'bg-slate-400' },
    ];

    const getIconForType = (type: string) => {
        switch (type) {
            case 'document': return <FileText className="h-5 w-5" />;
            case 'image': return <ImageIcon className="h-5 w-5" />;
            case 'text': return <File className="h-5 w-5" />;
            default: return <Brain className="h-5 w-5" />;
        }
    };

    return (
        <div className="max-w-7xl mx-auto space-y-8">
            {/* Header / Welcome */}
            <div className="flex flex-col gap-1">
                <h2 className="text-3xl font-bold text-slate-900 dark:text-white tracking-tight">Overview</h2>
                 <p className="text-slate-500 dark:text-slate-400">
                    Welcome back. Here's what's happening with {currentProject?.name || 'your project'}.
                </p>
            </div>

            {/* Stats Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                <StatsCard 
                    title="Total Memories" 
                    value={stats.memory_count} 
                    icon={Brain} 
                    trend="+12% from last week" 
                    trendUp={true}
                    colorClass="text-blue-600 dark:text-blue-400"
                    bgClass="bg-blue-50 dark:bg-blue-900/20"
                />
                <StatsCard 
                    title="Storage Used" 
                    value={formatStorage(stats.storage_used)} 
                    icon={HardDrive} 
                    subtext="45% of 100GB quota"
                    colorClass="text-purple-600 dark:text-purple-400"
                    bgClass="bg-purple-50 dark:bg-purple-900/20"
                />
                <StatsCard 
                    title="Active Nodes" 
                    value={stats.node_count} 
                    icon={Network} 
                    subtext="All systems operational"
                    colorClass="text-amber-600 dark:text-amber-400"
                    bgClass="bg-amber-50 dark:bg-amber-900/20"
                />
                <StatsCard 
                    title="Collaborators" 
                    value={stats.member_count} 
                    icon={Users} 
                    subtext="+2 new this week"
                    colorClass="text-indigo-600 dark:text-indigo-400"
                    bgClass="bg-indigo-50 dark:bg-indigo-900/20"
                />
            </div>

            {/* Main Content Split */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Left: Active Memories */}
                <div className="lg:col-span-2 flex flex-col gap-4">
                    <div className="flex items-center justify-between">
                        <h3 className="text-lg font-bold text-slate-900 dark:text-white">Active Memories</h3>
                        <button 
                            onClick={() => onNavigate('memories')}
                            className="text-sm text-blue-600 font-medium hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300"
                        >
                            View All
                        </button>
                    </div>
                    
                    <div className="bg-white dark:bg-[#1e2332] border border-slate-200 dark:border-slate-800 rounded-lg shadow-sm overflow-hidden">
                        <div className="overflow-x-auto">
                            <table className="w-full text-left text-sm">
                                <thead className="bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200 dark:border-slate-800">
                                    <tr>
                                        <th className="px-6 py-3 font-semibold text-slate-500 dark:text-slate-400">Name</th>
                                        <th className="px-6 py-3 font-semibold text-slate-500 dark:text-slate-400">Type</th>
                                        <th className="px-6 py-3 font-semibold text-slate-500 dark:text-slate-400">Status</th>
                                        <th className="px-6 py-3 font-semibold text-slate-500 dark:text-slate-400 text-right">Size</th>
                                        <th className="px-6 py-3 font-semibold text-slate-500 dark:text-slate-400"></th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                                    {isMemoriesLoading ? (
                                        <tr>
                                            <td colSpan={5} className="px-6 py-8 text-center text-slate-500">Loading memories...</td>
                                        </tr>
                                    ) : memories.length === 0 ? (
                                        <tr>
                                            <td colSpan={5} className="px-6 py-8 text-center text-slate-500">No memories found.</td>
                                        </tr>
                                    ) : (
                                        memories.slice(0, 5).map((memory) => (
                                            <tr key={memory.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors group">
                                                <td className="px-6 py-3">
                                                    <div className="flex items-center gap-3">
                                                        <div className="p-2 rounded bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400">
                                                            {getIconForType(memory.content_type)}
                                                        </div>
                                                        <div>
                                                            <div className="font-medium text-slate-900 dark:text-white truncate max-w-[200px]">{memory.title || 'Untitled Memory'}</div>
                                                            <div className="text-xs text-slate-500">Updated {formatDistanceToNow(new Date(memory.updated_at || memory.created_at), { addSuffix: true })}</div>
                                                        </div>
                                                    </div>
                                                </td>
                                                <td className="px-6 py-3 text-slate-600 dark:text-slate-300 capitalize">{memory.content_type}</td>
                                                <td className="px-6 py-3">
                                                    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${
                                                        memory.processing_status === 'COMPLETED' ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' : 
                                                        memory.processing_status === 'PROCESSING' ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400' :
                                                        'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-400'
                                                    }`}>
                                                        <span className={`w-1.5 h-1.5 rounded-full ${
                                                            memory.processing_status === 'COMPLETED' ? 'bg-green-500' :
                                                            memory.processing_status === 'PROCESSING' ? 'bg-blue-500 animate-pulse' :
                                                            'bg-slate-500'
                                                        }`}></span>
                                                        {memory.processing_status === 'COMPLETED' ? 'Synced' : memory.processing_status}
                                                    </span>
                                                </td>
                                                <td className="px-6 py-3 text-slate-600 dark:text-slate-300 text-right font-mono">
                                                    {formatStorage(memory.content.length)}
                                                </td>
                                                <td className="px-6 py-3 text-right">
                                                    <button className="text-slate-400 hover:text-blue-600 p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-700">
                                                        <MoreVertical className="h-5 w-5" />
                                                    </button>
                                                </td>
                                            </tr>
                                        ))
                                    )}
                                </tbody>
                            </table>
                        </div>
                        <div className="px-6 py-3 border-t border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-[#1e2332] flex justify-center">
                            <button 
                                onClick={() => onNavigate('memories')}
                                className="text-xs font-medium text-slate-500 hover:text-blue-600 flex items-center gap-1"
                            >
                                Show More <span className="text-base">↓</span>
                            </button>
                        </div>
                    </div>
                </div>

                {/* Right: Team & Activity */}
                <div className="flex flex-col gap-6">
                    {/* Team Card */}
                    <div className="bg-white dark:bg-[#1e2332] border border-slate-200 dark:border-slate-800 rounded-lg shadow-sm p-5">
                        <div className="flex items-center justify-between mb-4">
                            <h3 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wide">Team Online</h3>
                            <button className="p-1 text-slate-400 hover:text-blue-600 rounded hover:bg-slate-100 dark:hover:bg-slate-800">
                                <Plus className="h-5 w-5" />
                            </button>
                        </div>
                        <div className="flex flex-col gap-3">
                            {teamMembers.map((member, idx) => (
                                <div key={idx} className="flex items-center gap-3">
                                    <div className="relative">
                                        <div className="w-10 h-10 rounded-full bg-slate-200 dark:bg-slate-700 flex items-center justify-center text-slate-500 font-bold">
                                            {member.name.charAt(0)}
                                        </div>
                                        <span className={`absolute bottom-0 right-0 w-3 h-3 ${member.color} border-2 border-white dark:border-[#1e2332] rounded-full`}></span>
                                    </div>
                                    <div>
                                        <p className="text-sm font-medium text-slate-900 dark:text-white">{member.name}</p>
                                        <p className="text-xs text-slate-500">{member.status}</p>
                                    </div>
                                </div>
                            ))}
                        </div>
                        <button className="mt-4 w-full py-2 text-xs font-medium text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-slate-700 rounded hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors">
                            View All Members
                        </button>
                    </div>

                    {/* System Status */}
                    <div className="bg-blue-600 text-white rounded-lg shadow-lg p-5 relative overflow-hidden group">
                        <div className="absolute -right-6 -top-6 w-32 h-32 bg-white/10 rounded-full blur-2xl group-hover:bg-white/20 transition-all"></div>
                        <div className="relative z-10">
                            <h3 className="text-sm font-bold uppercase tracking-wide mb-3">System Status</h3>
                            <div className="flex items-start gap-3 mb-4">
                                <div className="p-1.5 bg-white/20 rounded">
                                    <Activity className="h-5 w-5" />
                                </div>
                                <div>
                                    <p className="text-sm font-medium">Auto-Indexing Active</p>
                                    <p className="text-xs text-blue-100 mt-1">AI is monitoring project updates.</p>
                                </div>
                            </div>
                            <div className="w-full bg-blue-900/50 h-1.5 rounded-full overflow-hidden">
                                <div className="bg-white h-full rounded-full animate-pulse w-full"></div>
                            </div>
                            <div className="flex justify-between text-[10px] mt-1 text-blue-200">
                                <span>Running...</span>
                                <span>100%</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};
