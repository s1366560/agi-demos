import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { Login } from '../../pages/Login';
import { useAuthStore } from '../../stores/auth';

vi.mock('../../stores/auth', () => ({
  useAuthStore: vi.fn(),
}));

vi.mock('@/components/shared/ui/LanguageSwitcher', () => ({
  LanguageSwitcher: () => <div data-testid="lang-switcher">Lang</div>,
}));

describe('Login', () => {
  const mockLogin = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    (useAuthStore as any).mockReturnValue({
      login: mockLogin,
      error: null,
      isLoading: false,
    });
  });

  it('renders login form', () => {
    render(<Login />);
    expect(screen.getAllByText('MemStack').length).toBeGreaterThan(0);
    expect(screen.getByText('Sign in to your account')).toBeInTheDocument();
  });

  it('handles input', () => {
    render(<Login />);
    const emailInput = screen.getByLabelText('Email');
    const passwordInput = screen.getByLabelText('Password');

    fireEvent.change(emailInput, { target: { value: 'test@example.com' } });
    fireEvent.change(passwordInput, { target: { value: 'password123' } });

    expect(emailInput).toHaveValue('test@example.com');
    expect(passwordInput).toHaveValue('password123');
  });

  it('toggles password visibility', () => {
    const { container } = render(<Login />);
    const passwordInput = screen.getByLabelText('Password');

    expect(passwordInput).toHaveAttribute('type', 'password');

    // Find the button inside the password input wrapper
    // The button contains the Eye icon
    const button = container.querySelector('button.absolute');
    fireEvent.click(button!);

    expect(passwordInput).toHaveAttribute('type', 'text');
  });

  it('submits form', async () => {
    render(<Login />);
    const emailInput = screen.getByLabelText('Email');
    const passwordInput = screen.getByLabelText('Password');
    const submitButton = screen.getByText('Sign In', { selector: 'button' });

    fireEvent.change(emailInput, { target: { value: 'test@example.com' } });
    fireEvent.change(passwordInput, { target: { value: 'password123' } });

    await waitFor(async () => {
      fireEvent.click(submitButton);
    });

    expect(mockLogin).toHaveBeenCalledWith('test@example.com', 'password123');
  });

  it('displays error', () => {
    (useAuthStore as any).mockReturnValue({
      login: mockLogin,
      error: 'Invalid credentials',
      isLoading: false,
    });
    render(<Login />);
    expect(screen.getByText('Invalid credentials')).toBeInTheDocument();
  });

  it('displays loading state', () => {
    (useAuthStore as any).mockReturnValue({
      login: mockLogin,
      error: null,
      isLoading: true,
    });
    render(<Login />);
    expect(screen.getByText('Signing in...')).toBeInTheDocument();
  });

  it('shows account recovery guidance via an actionable forgot-password dialog', async () => {
    const { container } = render(<Login />);

    expect(container.querySelectorAll('a[href="#"]')).toHaveLength(0);
    expect(
      screen.getByText('Password reset is handled by your organization administrator.')
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toHaveAccessibleDescription(
      'Password reset is handled by your organization administrator.'
    );

    expect(
      screen.getByText('New accounts are created through tenant invitations.')
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Forgot password?' }));
    expect(
      await screen.findByText(
        'If your organization uses single sign-on (SSO), sign in with your identity provider instead.'
      )
    ).toBeInTheDocument();

    expect(screen.queryByRole('button', { name: 'Register Now' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Privacy Policy' })).not.toBeInTheDocument();
  });

  it('auto fills demo credentials', () => {
    render(<Login />);
    const emailInput = screen.getByLabelText('Email');
    const passwordInput = screen.getByLabelText('Password');

    // Find admin credential button (using text content match)
    const adminCred = screen.getByText('admin@memstack.ai / adminpassword');
    // Click the parent container (which has the click handler)
    fireEvent.click(adminCred.parentElement!);

    expect(emailInput).toHaveValue('admin@memstack.ai');
    expect(passwordInput).toHaveValue('adminpassword');

    // Test user credential
    const userCred = screen.getByText('user@memstack.ai / userpassword');
    fireEvent.click(userCred.parentElement!);

    expect(emailInput).toHaveValue('user@memstack.ai');
    expect(passwordInput).toHaveValue('userpassword');
  });

  it('renders demo credentials as semantic buttons', () => {
    render(<Login />);
    const emailInput = screen.getByLabelText('Email');
    const passwordInput = screen.getByLabelText('Password');
    const adminDemoButton = screen.getByRole('button', { name: 'Use admin demo credentials' });
    const userDemoButton = screen.getByRole('button', { name: 'Use user demo credentials' });

    fireEvent.click(adminDemoButton);

    expect(emailInput).toHaveValue('admin@memstack.ai');
    expect(passwordInput).toHaveValue('adminpassword');

    fireEvent.click(userDemoButton);

    expect(emailInput).toHaveValue('user@memstack.ai');
    expect(passwordInput).toHaveValue('userpassword');
  });
});
