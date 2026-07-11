'use client';
import { useState } from 'react';
import { Users } from 'lucide-react';
import { useTranslation } from '@/lib/hooks/use-translation';
import { CreateWorkPackageDialog } from './CreateWorkPackageDialog';

export function CreateWorkPackageButton({ sourceId, sourceTitle }: { sourceId: string; sourceTitle: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex items-center gap-1.5 rounded-md px-2 py-1 text-[10px] font-semibold text-muted-foreground hover:text-primary"
      >
        <Users className="h-3 w-3" /> {t('controlPlane.workPackage.assignAction')}
      </button>
      <CreateWorkPackageDialog open={open} onOpenChange={setOpen} sourceId={sourceId} sourceTitle={sourceTitle} />
    </>
  );
}
