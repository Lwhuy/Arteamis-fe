'use client'

import { AppShell } from '@/components/layout/AppShell'
import { MembersPanel } from '@/components/members/members-panel'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { useRole } from '@/lib/hooks/use-role'
import { useTranslation } from '@/lib/hooks/use-translation'

export default function MembersPage() {
  const { t } = useTranslation()
  const { workspaceId } = useRole()

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto">
        <div className="p-6">
          <div className="max-w-4xl">
            <h1 className="text-2xl font-bold mb-6">{t('navigation.manageMembers')}</h1>
            {workspaceId ? (
              <MembersPanel workspaceId={workspaceId} />
            ) : (
              <div className="flex items-center justify-center py-12">
                <LoadingSpinner size="lg" />
              </div>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  )
}
