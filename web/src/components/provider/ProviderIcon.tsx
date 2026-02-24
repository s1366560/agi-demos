import React from 'react';

import { ProviderType } from '../../types/memory';

interface ProviderIconProps {
  providerType: ProviderType;
  size?: 'sm' | 'md' | 'lg' | 'xl' | undefined;
  className?: string | undefined;
}

const PROVIDER_CONFIG: Record<
  ProviderType,
  {
    icon: string;
    gradient: string;
    label: string;
    description: string;
  }
> = {
  openai: {
    icon: '🤖',
    gradient: 'from-green-400 to-blue-500',
    label: 'OpenAI',
    description: 'GPT-4, GPT-3.5, text-embedding',
  },
  anthropic: {
    icon: '🧠',
    gradient: 'from-orange-400 to-pink-500',
    label: 'Anthropic',
    description: 'Claude 3.5/4 Sonnet, Haiku',
  },
  gemini: {
    icon: '✨',
    gradient: 'from-blue-400 to-purple-500',
    label: 'Google Gemini',
    description: 'Gemini Pro, Flash',
  },
  dashscope: {
    icon: '🌐',
    gradient: 'from-red-400 to-orange-500',
    label: 'Alibaba Dashscope',
    description: 'Qwen-Max, Plus, Turbo',
  },
  kimi: {
    icon: '🌙',
    gradient: 'from-purple-400 to-indigo-500',
    label: 'Moonshot Kimi',
    description: 'Moonshot v1 系列',
  },
  deepseek: {
    icon: '🔍',
    gradient: 'from-blue-500 to-cyan-500',
    label: 'Deepseek',
    description: 'Deepseek-Chat, Coder',
  },
  minimax: {
    icon: '🧩',
    gradient: 'from-violet-500 to-purple-600',
    label: 'MiniMax',
    description: 'abab6.5-chat, embo-01',
  },
  zai: {
    icon: '🐲',
    gradient: 'from-yellow-400 to-red-500',
    label: 'ZhipuAI 智谱',
    description: 'GLM-4 系列',
  },
  cohere: {
    icon: '🔮',
    gradient: 'from-indigo-400 to-purple-500',
    label: 'Cohere',
    description: 'Command-R, embed, rerank',
  },
  mistral: {
    icon: '🌪️',
    gradient: 'from-orange-500 to-red-500',
    label: 'Mistral AI',
    description: 'Mistral-Large, Small',
  },
  groq: {
    icon: '⚡',
    gradient: 'from-purple-500 to-pink-500',
    label: 'Groq',
    description: 'Ultra-fast inference',
  },
  azure_openai: {
    icon: '☁️',
    gradient: 'from-blue-600 to-indigo-600',
    label: 'Azure OpenAI',
    description: 'Azure-hosted OpenAI',
  },
  bedrock: {
    icon: '🏔️',
    gradient: 'from-teal-500 to-green-600',
    label: 'AWS Bedrock',
    description: 'Claude, Titan, Llama',
  },
  vertex: {
    icon: '📊',
    gradient: 'from-green-500 to-blue-600',
    label: 'Google Vertex AI',
    description: 'Gemini on GCP',
  },
  ollama: {
    icon: '🦙',
    gradient: 'from-slate-500 to-gray-600',
    label: 'Ollama',
    description: 'Local models',
  },
  lmstudio: {
    icon: '🖥️',
    gradient: 'from-gray-500 to-slate-600',
    label: 'LM Studio',
    description: 'Local OpenAI-compatible',
  },
};

const SIZE_MAP: Record<string, string> = {
  sm: 'w-8 h-8 text-lg',
  md: 'w-10 h-10 text-xl',
  lg: 'w-12 h-12 text-2xl',
  xl: 'w-16 h-16 text-3xl',
};

export const ProviderIcon: React.FC<ProviderIconProps> = ({
  providerType,
  size = 'md',
  className = '',
}) => {
  const config = PROVIDER_CONFIG[providerType] || PROVIDER_CONFIG.openai;

  return (
    <div
      className={`${SIZE_MAP[size]} rounded-xl bg-gradient-to-br ${config.gradient} flex items-center justify-center shadow-lg ${className}`}
    >
      <span className="filter drop-shadow-md">{config.icon}</span>
    </div>
  );
};

export { PROVIDER_CONFIG };
