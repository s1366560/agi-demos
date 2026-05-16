export const getStatusColor = (status: string) => {
  switch (status) {
    case 'creating':
    case 'provisioning':
    case 'pending':
      return 'blue';
    case 'deploying':
    case 'restarting':
    case 'scaling':
    case 'learning':
    case 'in_progress':
      return 'orange';
    case 'running':
    case 'success':
      return 'green';
    case 'stopped':
      return 'default';
    case 'error':
    case 'failed':
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
