import { describe, expect, it } from 'vitest';
import type { RichPageContext } from '../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import { boardAddress, boardLocation } from '../../../../plugins/business/workspace/ui/signed/boardLocation';

const scope: RichPageContext = {
  tenantId: 't', projectId: 'p', target: 'web',platform:'web',locale:'en',
  pathname:'/tenant/t/project/p/workspaces/my%20board/tasks/my%20task',
  search:'?conversationId=c',hash:'#activity',commands:[],deviceTools:[],
};

describe('workspace deep links', () => {
  it('restores the original task panel and returns to its owning board', () => {
    const {id,tab,params} = boardLocation(scope);
    expect(id).toBe('my board');
    expect(tab).toBe('goals');
    expect(params.get('taskId')).toBe('my task');
    expect(boardAddress(scope,params,scope.hash)).toBe(scope.pathname+scope.search+scope.hash);
    params.delete('taskId');
    expect(boardAddress(scope,params,'')).toBe('/tenant/t/project/p/workspaces/my%20board/tasks?conversationId=c');
  });
  it('reflects native tab changes and keeps legacy blackboard URLs', () => {
    const ctx = {...scope,pathname:'/project/p/blackboard',search:'?workspaceId=w&tab=files'};
    const {params,tab} = boardLocation(ctx);
    expect(tab).toBe('files');
    params.set('tab','discussion');
    expect(boardAddress(ctx,params,'')).toBe('/project/p/blackboard?workspaceId=w&tab=discussion');
    expect(boardAddress({...ctx,pathname:'/workspaces/w'},params,'')).toBe('/workspaces/w/posts');
  });
});
