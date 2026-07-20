import { describe, expect, it } from 'vitest';

import {
  NotificationCenter,
  NotificationProvider,
  useNotifications,
} from '../../../components/common/NotificationCenter';
import { fireEvent, render, screen } from '../../utils';

const NotificationSeeder = () => {
  const { pushNotification } = useNotifications();

  return (
    <button
      type="button"
      onClick={() => {
        pushNotification({
          kind: 'info',
          title: 'Index complete',
          body: 'The workspace index finished.',
        });
      }}
    >
      Add notification
    </button>
  );
};

describe('NotificationCenter', () => {
  it('closes the notification panel on Escape', () => {
    render(
      <NotificationProvider>
        <NotificationSeeder />
        <NotificationCenter />
      </NotificationProvider>
    );

    fireEvent.click(screen.getByRole('button', { name: 'Add notification' }));
    fireEvent.click(screen.getByRole('button', { name: /Notifications/i }));
    expect(
      screen.getByRole('dialog', { name: /notifications\.title|Notifications/ })
    ).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(
      screen.queryByRole('dialog', { name: /notifications\.title|Notifications/ })
    ).not.toBeInTheDocument();
  });
});
