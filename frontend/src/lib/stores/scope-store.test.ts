import { describe, it, expect, beforeEach } from 'vitest';
import { useScopeStore } from './scope-store';

describe('useScopeStore', () => {
  beforeEach(() => useScopeStore.setState({ scope: 'personal' }));

  it('defaults to personal', () => {
    expect(useScopeStore.getState().scope).toBe('personal');
  });

  it('setScope switches scope', () => {
    useScopeStore.getState().setScope('company');
    expect(useScopeStore.getState().scope).toBe('company');
  });

  it('toggle flips between personal and company', () => {
    useScopeStore.getState().toggle();
    expect(useScopeStore.getState().scope).toBe('company');
    useScopeStore.getState().toggle();
    expect(useScopeStore.getState().scope).toBe('personal');
  });
});
