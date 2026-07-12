'use client';
import { ListChecks } from 'lucide-react';
import { useCreateRule } from '@/lib/hooks/use-governance';
import { useTranslation } from '@/lib/hooks/use-translation';

// Promote a belief into a durable Rule (loop step 6). A rule is derived from one
// or more beliefs; here we one-click promote the single belief this button sits
// on, using its title as both the rule title and statement seed.
export function CreateRuleButton({ beliefId, beliefTitle }: { beliefId: string; beliefTitle: string }) {
  const { t } = useTranslation();
  const create = useCreateRule();
  return (
    <button
      type="button"
      disabled={create.isPending}
      onClick={() => create.mutate({ title: beliefTitle, statement: beliefTitle, belief_ids: [beliefId] })}
      className="flex items-center gap-1.5 rounded-md px-2 py-1 text-[10px] font-semibold text-muted-foreground hover:text-primary"
    >
      <ListChecks className="h-3 w-3" /> {t('controlPlane.brain.createRule')}
    </button>
  );
}
