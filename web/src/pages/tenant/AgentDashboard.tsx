import React, { useState, memo, useCallback } from 'react';

import { useTranslation } from 'react-i18next';

import {
  Brain,
  Terminal,
  Globe,
  Palette,
  BarChart,
  FileText,
  Languages,
  Table,
  Mail,
  CheckCircle,
  Puzzle,
  Plus,
} from 'lucide-react';

interface SubAgent {
  id: string;
  title: string;
  description: string;
  tags: string[];
  active: boolean;
  icon: React.ElementType;
  colorClass: string;
  iconBgClass: string;
}

interface Skill {
  id: string;
  name: string;
  version: string;
  icon: React.ElementType;
}

// Hoist static data to module scope to avoid re-creation on each render
const DEFAULT_SUB_AGENTS: SubAgent[] = [
  {
    id: 'code-architect',
    title: 'Code Architect',
    description: 'Expert in refactoring, debugging, and cross-language pattern detection.',
    tags: ['Python', 'GitOps', 'CI/CD'],
    active: true,
    icon: Terminal,
    colorClass: 'text-blue-600 dark:text-blue-400',
    iconBgClass: 'bg-blue-100 dark:bg-blue-900/30',
  },
  {
    id: 'deep-researcher',
    title: 'Deep Researcher',
    description: 'Synthesizes large datasets into structured executive summaries and reports.',
    tags: ['Web Search', 'PDF Analysis', 'NLP'],
    active: true,
    icon: Globe,
    colorClass: 'text-purple-600 dark:text-purple-400',
    iconBgClass: 'bg-purple-100 dark:bg-purple-900/30',
  },
  {
    id: 'creative-strategist',
    title: 'Creative Strategist',
    description: 'Generates marketing copy, UI concepts, and brand narratives.',
    tags: ['Copywriting', 'Branding'],
    active: false,
    icon: Palette,
    colorClass: 'text-orange-600 dark:text-orange-400',
    iconBgClass: 'bg-orange-100 dark:bg-orange-900/30',
  },
  {
    id: 'data-analyst',
    title: 'Data Analyst',
    description: 'Statistical modeling and anomaly detection from structured SQL sources.',
    tags: ['SQL', 'Statistics'],
    active: false,
    icon: BarChart,
    colorClass: 'text-teal-600 dark:text-teal-400',
    iconBgClass: 'bg-teal-100 dark:bg-teal-900/30',
  },
];

const SKILLS: Skill[] = [
  { id: 'doc-sum', name: 'Document Summarizer', version: 'Core Logic Module v1.2', icon: FileText },
  {
    id: 'multi-lang',
    name: 'Multi-Lingual Bridge',
    version: 'Language Suite v4.0',
    icon: Languages,
  },
  { id: 'excel-proc', name: 'Excel/CSV Processor', version: 'Data Utils v2.1', icon: Table },
  { id: 'email-syn', name: 'Email Synthesizer', version: 'Comm Engine v1.0', icon: Mail },
];

type AgentDashboardProps = Record<string, never>;

// Sub-component: SubAgentCard with memo for performance optimization
const SubAgentCard = memo<{
  agent: SubAgent;
  onToggle: (id: string) => void;
}>(({ agent, onToggle }) => {
  return (
    <div
      className={`rounded-xl p-5 relative overflow-hidden transition-all border-2 ${
        agent.active
          ? 'bg-white dark:bg-slate-800 border-blue-600 shadow-lg shadow-blue-600/5'
          : 'bg-white/50 dark:bg-slate-800/50 border-slate-200 dark:border-slate-700 opacity-80 hover:opacity-100 hover:border-slate-300 dark:hover:border-slate-600'
      }`}
    >
      <div className="flex justify-between items-start mb-4">
        <div className={`p-2 rounded-lg ${agent.iconBgClass} ${agent.colorClass}`}>
          <agent.icon className="h-6 w-6" />
        </div>
        {agent.active ? (
          <div className="bg-blue-600 text-white text-[10px] font-bold px-2 py-0.5 rounded-full uppercase">
            Active
          </div>
        ) : (
          <button
            onClick={() => {
              onToggle(agent.id);
            }}
            className="text-blue-600 dark:text-blue-400 text-[10px] font-bold uppercase tracking-tight hover:underline"
          >
            Activate
          </button>
        )}
      </div>
      <h4 className="font-bold text-lg mb-1 text-slate-900 dark:text-white">{agent.title}</h4>
      <p className="text-sm text-slate-500 dark:text-slate-400 mb-4 leading-relaxed min-h-[40px]">
        {agent.description}
      </p>

      {agent.active && (
        <div className="flex flex-wrap gap-2">
          {agent.tags.map((tag) => (
            <span
              key={tag}
              className="px-2 py-1 bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 text-[10px] rounded font-medium"
            >
              {tag}
            </span>
          ))}
        </div>
      )}
    </div>
  );
});
SubAgentCard.displayName = 'SubAgentCard';

// Sub-component: SkillCard with memo for performance optimization
const SkillCard = memo<{ skill: Skill }>(({ skill }) => {
  return (
    <div className="flex items-center gap-3">
      <div className="w-8 h-8 rounded bg-slate-100 dark:bg-slate-700 flex items-center justify-center text-slate-600 dark:text-slate-400">
        <skill.icon className="h-4 w-4" />
      </div>
      <div className="flex-1">
        <p className="text-sm font-semibold text-slate-900 dark:text-white">{skill.name}</p>
        <p className="text-[10px] text-slate-500">{skill.version}</p>
      </div>
      <CheckCircle className="text-green-500 h-4 w-4" />
    </div>
  );
});
SkillCard.displayName = 'SkillCard';

// Sub-component: EngineConfigCard with memo for performance optimization
interface EngineConfigCardProps {
  label: string;
  description: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}

const EngineConfigCard = memo<EngineConfigCardProps>(
  ({ label, description, checked, onChange }) => {
    return (
      <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl p-6 flex items-start gap-4">
        <div className="pt-1 flex-shrink-0">
          <label className="inline-flex relative items-center cursor-pointer">
            <input
              type="checkbox"
              checked={checked}
              onChange={(e) => {
                onChange(e.target.checked);
              }}
              className="sr-only peer"
            />
            <div className="w-11 h-6 bg-slate-300 dark:bg-slate-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
          </label>
        </div>
        <div>
          <h4 className="font-bold text-sm text-slate-900 dark:text-white">{label}</h4>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">{description}</p>
        </div>
      </div>
    );
  }
);
EngineConfigCard.displayName = 'EngineConfigCard';

// Main component with React.memo for performance optimization
export const AgentDashboard: React.FC<AgentDashboardProps> = memo(() => {
  const { t: _t } = useTranslation();

  const [subAgents, setSubAgents] = useState<SubAgent[]>(DEFAULT_SUB_AGENTS);
  const [autoLearning, setAutoLearning] = useState(true);
  const [browserAccess, setBrowserAccess] = useState(true);

  const toggleAgent = useCallback((id: string) => {
    setSubAgents((prev) =>
      prev.map((agent) => (agent.id === id ? { ...agent, active: !agent.active } : agent))
    );
  }, []);

  return (
    <div className="max-w-full mx-auto pb-24">
      <header className="mb-8">
        <div className="flex items-center gap-3 mb-2">
          <div className="bg-blue-600 rounded-lg p-2">
            <Brain className="text-white h-6 w-6" />
          </div>
          <h1 className="text-xl font-black tracking-tight uppercase text-slate-900 dark:text-white">
            SubAgent Platform
          </h1>
        </div>
        <div className="max-w-2xl">
          <h2 className="text-3xl font-bold text-slate-900 dark:text-white mb-2">
            Configure Your Intelligence Core
          </h2>
          <p className="text-slate-500 dark:text-slate-400">
            Activate your first SubAgents and define the foundational skills for your enterprise
            tenant.
          </p>
        </div>
      </header>

      <div className="grid grid-cols-12 gap-8">
        {/* Main Content */}
        <div className="col-span-12 lg:col-span-8 space-y-8">
          {/* Available SubAgents */}
          <section>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-bold uppercase tracking-wider text-slate-400">
                Available SubAgents
              </h3>
              <span className="text-xs text-slate-500">
                {subAgents.filter((a) => a.active).length} selected
              </span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {subAgents.map((agent) => (
                <SubAgentCard key={agent.id} agent={agent} onToggle={toggleAgent} />
              ))}
            </div>
          </section>

          {/* Global Engine Configuration */}
          <section className="space-y-4">
            <h3 className="text-sm font-bold uppercase tracking-wider text-slate-400">
              Global Engine Configuration
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <EngineConfigCard
                label="Auto-Learning Experience Engine"
                description="Allow the platform to discover and optimize new workflow patterns from user interactions automatically."
                checked={autoLearning}
                onChange={setAutoLearning}
              />
              <EngineConfigCard
                label="Universal Browser Access"
                description="Enables agents to navigate the live web for real-time information retrieval and task execution."
                checked={browserAccess}
                onChange={setBrowserAccess}
              />
            </div>
          </section>
        </div>

        {/* Sidebar: Skill Registry */}
        <div className="col-span-12 lg:col-span-4">
          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden sticky top-6">
            <div className="p-5 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between bg-slate-50 dark:bg-slate-900/50">
              <h3 className="font-bold text-sm uppercase tracking-wide text-slate-700 dark:text-slate-200">
                Standard Skill Registry
              </h3>
              <Puzzle className="text-slate-400 h-5 w-5" />
            </div>
            <div className="p-5 space-y-5">
              <p className="text-xs text-slate-500 dark:text-slate-400">
                These basic skills will be available to all active SubAgents by default.
              </p>
              <div className="space-y-4">
                {SKILLS.map((skill) => (
                  <SkillCard key={skill.id} skill={skill} />
                ))}
              </div>
              <div className="pt-4 border-t border-slate-100 dark:border-slate-700">
                <button className="w-full py-2 bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 rounded-lg text-xs font-bold transition-colors text-slate-700 dark:text-slate-200 flex items-center justify-center gap-2">
                  <Plus className="h-3 w-3" />
                  Add Custom Skills
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
});
AgentDashboard.displayName = 'AgentDashboard';

// Export static data for testing
export { DEFAULT_SUB_AGENTS, SKILLS };
