export const graphService = {
  optimizeContent(payload: { content: string }) {
    return window.memstack.invoke('optimize-content', payload) as Promise<{ content: string }>;
  },
};
