import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ScopeSwitch } from './ScopeSwitch';
import { useScopeStore } from '@/lib/stores/scope-store';

// i18n: t returns the key by default in test setup (see existing tests e.g. AppSidebar.test.tsx)
describe('ScopeSwitch', () => {
  beforeEach(() => useScopeStore.setState({ scope: 'personal' }));

  it('clicking Company sets scope to company', () => {
    render(<ScopeSwitch />);
    fireEvent.click(screen.getByRole('button', { name: /company/i }));
    expect(useScopeStore.getState().scope).toBe('company');
  });

  it('reflects active scope via aria-pressed', () => {
    useScopeStore.setState({ scope: 'company' });
    render(<ScopeSwitch />);
    expect(screen.getByRole('button', { name: /company/i })).toHaveAttribute('aria-pressed', 'true');
  });
});
