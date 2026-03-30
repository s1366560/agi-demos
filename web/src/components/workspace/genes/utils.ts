export const getCategoryColor = (category: string) => {
  switch (category) {
    case 'skill':
      return 'blue';
    case 'knowledge':
      return 'green';
    case 'tool':
      return 'orange';
    case 'workflow':
      return 'purple';
    default:
      return 'default';
  }
};
