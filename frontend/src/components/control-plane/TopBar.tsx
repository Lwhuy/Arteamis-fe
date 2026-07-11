'use client';
import { ScopeSwitch } from './ScopeSwitch';
import { Logo } from '@/components/common/Logo';

export function TopBar() {
  return (
    <header className="flex h-14 flex-shrink-0 items-center gap-4 border-b border-border bg-background px-4">
      <Logo />
      <div className="mx-auto"><ScopeSwitch /></div>
    </header>
  );
}
