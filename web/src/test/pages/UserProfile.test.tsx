import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { UserProfile } from '../../pages/UserProfile';
import { authAPI } from '../../services/api';
import { useAuthStore } from '../../stores/auth';

import type { User } from '../../types/memory';

const confirmActionMock = vi.hoisted(() => vi.fn());

vi.mock('../../services/api', () => ({
  authAPI: {
    updateProfile: vi.fn(),
  },
}));

vi.mock('../../stores/auth', () => ({
  useAuthStore: vi.fn(),
}));

vi.mock('../../utils/confirmAction', () => ({
  confirmAction: confirmActionMock,
}));

const baseUser: User = {
  id: 'user-1',
  email: 'ada@example.com',
  name: 'Ada Lovelace',
  roles: ['user'],
  is_active: true,
  created_at: '2024-01-01T00:00:00Z',
  preferred_language: 'en-US',
  profile: {
    job_title: 'Analyst',
    department: 'Engineering',
    bio: 'Computing pioneer',
    phone: '+1 555 0100',
    location: 'London',
    language: 'English (US)',
    timezone: 'London (UTC)',
    avatar_url: 'https://example.com/ada.png',
  },
};

describe('UserProfile', () => {
  const setUser = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    confirmActionMock.mockResolvedValue(false);
    (useAuthStore as any).mockReturnValue({
      user: baseUser,
      setUser,
    });
  });

  const renderProfile = () =>
    render(
      <MemoryRouter>
        <UserProfile />
      </MemoryRouter>
    );

  it('activates section tabs and exposes the password route', () => {
    renderProfile();

    const securityTab = screen.getByRole('button', { name: 'user_profile.tabs.security' });
    fireEvent.click(securityTab);

    expect(securityTab).toHaveAttribute('aria-controls', 'profile-section-security');
    expect(
      screen.getByRole('link', { name: 'user_profile.security.change_password' })
    ).toHaveAttribute('href', '/force-change-password');
  });

  it('resets unsaved edits after confirming the discard dialog', async () => {
    confirmActionMock.mockResolvedValueOnce(true);
    renderProfile();

    fireEvent.change(screen.getByDisplayValue('Ada Lovelace'), {
      target: { value: 'Grace Hopper' },
    });
    fireEvent.change(screen.getByDisplayValue('Analyst'), {
      target: { value: 'Principal Engineer' },
    });

    fireEvent.click(screen.getAllByRole('button', { name: 'user_profile.buttons.cancel' })[0]!);

    await waitFor(() => {
      expect(confirmActionMock).toHaveBeenCalledOnce();
      expect(screen.getByDisplayValue('Ada Lovelace')).toBeInTheDocument();
    });
    expect(screen.getByDisplayValue('Analyst')).toBeInTheDocument();
  });

  it('resets a clean form immediately without asking for confirmation', () => {
    renderProfile();

    fireEvent.click(screen.getAllByRole('button', { name: 'user_profile.buttons.cancel' })[0]!);

    expect(confirmActionMock).not.toHaveBeenCalled();
    expect(screen.getByDisplayValue('Ada Lovelace')).toBeInTheDocument();
  });

  it('focuses the avatar URL field from the avatar action', () => {
    renderProfile();

    fireEvent.click(screen.getByRole('button', { name: 'Change avatar' }));

    expect(screen.getByLabelText('user_profile.basic.avatar_url')).toHaveFocus();
  });

  it('submits a UserUpdate payload and stores the mapped user', async () => {
    const updatedUser: User = {
      ...baseUser,
      name: 'Grace Hopper',
      preferred_language: 'zh-CN',
      profile: {
        ...baseUser.profile,
        avatar_url: 'https://example.com/grace.png',
        job_title: 'Principal Engineer',
      },
    };
    vi.mocked(authAPI.updateProfile).mockResolvedValueOnce(updatedUser);

    renderProfile();

    fireEvent.change(screen.getByDisplayValue('Ada Lovelace'), {
      target: { value: 'Grace Hopper' },
    });
    fireEvent.change(screen.getByDisplayValue('Analyst'), {
      target: { value: 'Principal Engineer' },
    });
    fireEvent.change(screen.getByLabelText('user_profile.basic.avatar_url'), {
      target: { value: 'https://example.com/grace.png' },
    });
    fireEvent.change(screen.getByLabelText('user_profile.preferences.language'), {
      target: { value: 'zh-CN' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'user_profile.buttons.save' }));

    await waitFor(() => {
      expect(authAPI.updateProfile).toHaveBeenCalledWith({
        name: 'Grace Hopper',
        profile: expect.objectContaining({
          avatar_url: 'https://example.com/grace.png',
          job_title: 'Principal Engineer',
          location: 'London',
        }),
        preferred_language: 'zh-CN',
      });
    });
    expect(setUser).toHaveBeenCalledWith(updatedUser);
  });
});
