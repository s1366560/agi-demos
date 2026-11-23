// Shared status -> tag color mapping for instances, clusters, deploys and runtimes.
export const getStatusColor = (status: string) => {
  switch (status.toLowerCase()) {
    case 'creating':
    case 'provisioning':
    case 'pending':
    case 'initializing':
      return 'blue';
    case 'deploying':
    case 'restarting':
    case 'scaling':
    case 'learning':
    case 'in_progress':
    case 'warning':
    case 'maintenance':
    case 'degraded':
    case 'paused':
      return 'orange';
    case 'running':
    case 'success':
    case 'active':
    case 'connected':
    case 'healthy':
    case 'ready':
    case 'executing':
      return 'green';
    case 'stopped':
    case 'inactive':
      return 'default';
    case 'error':
    case 'failed':
    case 'unhealthy':
    case 'disconnected':
      return 'red';
    case 'deleting':
    case 'terminated':
    case 'cancelled':
      return 'gray';
    default:
      return 'default';
  }
};

export const formatDate = (dateString: string | Date | undefined | null) => {
  if (!dateString) return '-';
  try {
    return new Date(dateString).toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return String(dateString);
  }
};
