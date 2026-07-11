import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type Scope = 'personal' | 'company';

interface ScopeState {
  scope: Scope;
  hasHydrated: boolean;
  setScope: (s: Scope) => void;
  toggle: () => void;
  setHasHydrated: (b: boolean) => void;
}

export const useScopeStore = create<ScopeState>()(
  persist(
    (set, get) => ({
      scope: 'personal',
      hasHydrated: false,
      setScope: (scope) => set({ scope }),
      toggle: () => set({ scope: get().scope === 'personal' ? 'company' : 'personal' }),
      setHasHydrated: (hasHydrated) => set({ hasHydrated }),
    }),
    {
      name: 'scope-storage',
      partialize: (s) => ({ scope: s.scope }),
      onRehydrateStorage: () => (state) => state?.setHasHydrated(true),
    },
  ),
);
