'use client'

import { useMemo, useState } from 'react'

import { AppShell } from '@/components/layout/AppShell'
import { ProjectList } from './components/ProjectList'
import { RecentlyViewed } from './components/RecentlyViewed'
import { Button } from '@/components/ui/button'
import { Plus, RefreshCw, LayoutGrid, List } from 'lucide-react'
import { useProjects } from '@/lib/hooks/use-projects'
import { CreateProjectDialog } from '@/components/projects/CreateProjectDialog'
import { Input } from '@/components/ui/input'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useProjectViewStore } from '@/lib/stores/project-view-store'

export default function ProjectsPage() {
  const { t } = useTranslation()
  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const viewMode = useProjectViewStore((state) => state.viewMode)
  const setViewMode = useProjectViewStore((state) => state.setViewMode)
  const { data: notebooks, isLoading, refetch } = useProjects(false)
  const { data: archivedNotebooks } = useProjects(true)

  const normalizedQuery = searchTerm.trim().toLowerCase()

  const filteredActive = useMemo(() => {
    if (!notebooks) {
      return undefined
    }
    if (!normalizedQuery) {
      return notebooks
    }
    return notebooks.filter((notebook) =>
      notebook.name.toLowerCase().includes(normalizedQuery)
    )
  }, [notebooks, normalizedQuery])

  const filteredArchived = useMemo(() => {
    if (!archivedNotebooks) {
      return undefined
    }
    if (!normalizedQuery) {
      return archivedNotebooks
    }
    return archivedNotebooks.filter((notebook) =>
      notebook.name.toLowerCase().includes(normalizedQuery)
    )
  }, [archivedNotebooks, normalizedQuery])

  const hasArchived = (archivedNotebooks?.length ?? 0) > 0
  const isSearching = normalizedQuery.length > 0

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto">
        <div className="p-6 space-y-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <h1 className="text-2xl font-bold">{t('projects.title')}</h1>
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              <RefreshCw className="h-4 w-4" />
            </Button>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
            <div className="flex items-center rounded-md border p-0.5">
              <Button
                variant={viewMode === 'tile' ? 'secondary' : 'ghost'}
                size="sm"
                onClick={() => setViewMode('tile')}
                aria-label={t('notebooks.tileView')}
                aria-pressed={viewMode === 'tile'}
                title={t('notebooks.tileView')}
              >
                <LayoutGrid className="h-4 w-4" />
              </Button>
              <Button
                variant={viewMode === 'list' ? 'secondary' : 'ghost'}
                size="sm"
                onClick={() => setViewMode('list')}
                aria-label={t('notebooks.listView')}
                aria-pressed={viewMode === 'list'}
                title={t('notebooks.listView')}
              >
                <List className="h-4 w-4" />
              </Button>
            </div>
            <Input
              id="notebook-search"
              name="notebook-search"
              value={searchTerm}
              onChange={(event) => setSearchTerm(event.target.value)}
              placeholder={t('notebooks.searchPlaceholder')}
              autoComplete="off"
              aria-label={t('common.accessibility.searchNotebooks') || "Search notebooks"}
              className="w-full sm:w-64"
            />
            <Button onClick={() => setCreateDialogOpen(true)}>
              <Plus className="h-4 w-4 mr-2" />
              {t('projects.newProject')}
            </Button>
          </div>
        </div>
        
        <div className="space-y-8">
          <RecentlyViewed />

          <ProjectList 
            notebooks={filteredActive} 
            isLoading={isLoading}
            title={t('notebooks.activeNotebooks')}
            emptyTitle={isSearching ? t('common.noMatches') : undefined}
            emptyDescription={isSearching ? t('common.tryDifferentSearch') : undefined}
            onAction={!isSearching ? () => setCreateDialogOpen(true) : undefined}
            actionLabel={!isSearching ? t('projects.newProject') : undefined}
          />
          
          {hasArchived && (
            <ProjectList 
              notebooks={filteredArchived} 
              isLoading={false}
              title={t('notebooks.archivedNotebooks')}
              collapsible
              emptyTitle={isSearching ? t('common.noMatches') : undefined}
              emptyDescription={isSearching ? t('common.tryDifferentSearch') : undefined}
            />
          )}
        </div>
        </div>
      </div>

      <CreateProjectDialog
        open={createDialogOpen}
        onOpenChange={setCreateDialogOpen}
      />
    </AppShell>
  )
}
