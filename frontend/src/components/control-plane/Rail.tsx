'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { MessageSquare, Network, FileText, Mic, Link2, Settings } from 'lucide-react';
import { useTranslation } from '@/lib/hooks/use-translation';
import { cn } from '@/lib/utils';

const primary = [
  { href: '/control-plane', labelKey: 'controlPlane.rail.chat', icon: MessageSquare },
  { href: '/search', labelKey: 'controlPlane.rail.brain', icon: Network },
];
const legacy = [
  { href: '/sources', labelKey: 'controlPlane.rail.sources', icon: FileText },
  { href: '/podcasts', labelKey: 'controlPlane.rail.podcasts', icon: Mic },
  { href: '/connections', labelKey: 'controlPlane.rail.connections', icon: Link2 },
];

function RailLink({ href, labelKey, icon: Icon }: { href: string; labelKey: string; icon: typeof MessageSquare }) {
  const { t } = useTranslation();
  const pathname = usePathname();
  const active = href === '/control-plane' ? pathname === '/control-plane' : pathname?.startsWith(href);
  return (
    <Link
      href={href}
      aria-label={t(labelKey)}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'grid h-11 w-11 place-items-center rounded-xl text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        active && 'bg-accent text-accent-foreground',
      )}
    >
      <Icon className="h-5 w-5" />
    </Link>
  );
}

export function Rail() {
  const { t } = useTranslation();
  return (
    <nav aria-label={t('controlPlane.rail.chat')} className="flex w-[66px] flex-shrink-0 flex-col items-center gap-1 border-r border-border bg-background py-3">
      {primary.map((i) => <RailLink key={i.href} {...i} />)}
      <div className="my-1.5 w-8 border-t border-dashed border-border pt-1.5 text-center text-[8px] uppercase tracking-wide text-muted-foreground">
        {t('controlPlane.rail.legacy')}
      </div>
      {legacy.map((i) => <RailLink key={i.href} {...i} />)}
      <div className="flex-1" />
      <RailLink href="/settings" labelKey="controlPlane.rail.settings" icon={Settings} />
    </nav>
  );
}
