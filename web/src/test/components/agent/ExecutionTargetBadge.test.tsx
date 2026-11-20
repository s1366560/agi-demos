import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import {
  ExecutionTargetBadge,
  ExecutionTargetFilterBar,
} from '@/components/execution-target/ExecutionTargetBadge';
import { executionTargetOf } from '@/components/execution-target/executionTargetModel';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) =>
      ({
        'agent.executionTarget.local': '此计算机',
        'agent.executionTarget.cloud': '云端',
        'agent.executionTarget.all': '全部',
        'agent.executionTarget.filterLabel': '执行位置',
        'agent.executionTarget.defaultEnvironment': '默认环境',
        'agent.executionTarget.localDirectory': '本地目录',
      })[key] ?? fallback ?? key,
  }),
}));

describe('execution target presentation', () => {
  it('defaults missing runs to the cloud badge and default environment', () => {
    expect(executionTargetOf(undefined)).toBe('cloud');
    render(<ExecutionTargetBadge />);
    expect(screen.getByText('云端')).toBeInTheDocument();
    expect(screen.getByText('默认环境')).toBeInTheDocument();
  });

  it('shows this computer and the local directory label', () => {
    render(<ExecutionTargetBadge executionTarget="local" localRootLabel="agi-demos" />);
    expect(screen.getByText('此计算机')).toBeInTheDocument();
    expect(screen.getByText('agi-demos')).toBeInTheDocument();
  });

  it('reports the selected filter and does not offer a local create action', async () => {
    const onChange = vi.fn();
    render(<ExecutionTargetFilterBar value="all" onChange={onChange} />);
    fireEvent.click(screen.getByRole('button', { name: '此计算机' }));
    expect(onChange).toHaveBeenCalledWith('local');
    expect(screen.queryByRole('button', { name: /新建|创建/ })).not.toBeInTheDocument();
  });
});
