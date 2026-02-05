/**
 * HITL Debug Script - Browser Console Helper
 * 
 * 在浏览器控制台中使用以下命令检查 HITL 状态：
 * 
 * 1. 检查 pending HITL 请求：
 *    hitlDebug.list()
 * 
 * 2. 检查特定请求详情：
 *    hitlDebug.get('request_id')
 * 
 * 3. 模拟提交响应：
 *    hitlDebug.submit('request_id', 'clarification', { answer: 'test' })
 * 
 * 4. 清除所有 HITL：
 *    hitlDebug.clear()
 * 
 * 5. 检查 store 状态：
 *    hitlDebug.state
 * 
 * 6. 启用调试日志：
 *    hitlDebug.enableLogs()
 */

(function() {
  'use strict';

  const HITL_DEBUG = {
    version: '1.0.0',
    
    getStore() {
      const store = window.__ZUSTAND_STORES__?.unifiedHitlStore 
        || window.unifiedHitlStore
        || window.__UNIFIED_HITL_STORE__;
      
      if (!store) {
        console.error('[HITL Debug] Store not found.');
        return null;
      }
      return store;
    },

    list() {
      const store = this.getStore();
      if (!store) return;

      const state = store.getState?.() || store;
      const requests = state.pendingRequests;
      
      if (!requests || requests.size === 0) {
        console.log('%c[HITL Debug] No pending requests', 'color: #52c41a');
        return;
      }

      console.log('%c[HITL Debug] Pending Requests:', 'color: #1890ff; font-weight: bold');
      
      const table = [];
      requests.forEach((req, id) => {
        table.push({
          requestId: id,
          type: req.hitlType,
          status: req.status,
          question: req.question?.substring(0, 50) + '...',
          createdAt: new Date(req.createdAt).toLocaleTimeString(),
          remaining: req.expiresAt ? Math.floor((new Date(req.expiresAt) - Date.now()) / 1000) + 's' : 'N/A'
        });
      });
      
      console.table(table);
    },

    get(requestId) {
      const store = this.getStore();
      if (!store) return;

      const state = store.getState?.() || store;
      const request = state.pendingRequests?.get(requestId);
      
      if (!request) {
        console.error(`[HITL Debug] Request ${requestId} not found`);
        return null;
      }

      console.log('[HITL Debug] Request:', request);
      return request;
    },

    help() {
      console.log(`%cHITL Debug Tool
Available Commands:
  hitlDebug.list()              - List all pending HITL requests
  hitlDebug.get(requestId)      - Get request details
  hitlDebug.state               - Get store state
  hitlDebug.help()              - Show this help
      `, 'color: #1890ff;');
    }
  };

  window.hitlDebug = HITL_DEBUG;
  console.log('%c[HITL Debug] Loaded. Type hitlDebug.help() for usage.', 'color: #52c41a');
})();
