"use client"

import { Control, Controller } from "react-hook-form"
import { Lock, Users, Building2 } from "lucide-react"
import { useTranslation } from "@/lib/hooks/use-translation"
import { FormSection } from "@/components/ui/form-section"
import { CheckboxList } from "@/components/ui/checkbox-list"
import { Checkbox } from "@/components/ui/checkbox"
import { Transformation } from "@/lib/types/transformations"
import { SettingsResponse } from "@/lib/types/api"
import { cn } from "@/lib/utils"

interface CreateSourceFormData {
  type: 'link' | 'upload' | 'text'
  title?: string
  url?: string
  content?: string
  file?: FileList | File
  notebooks?: string[]
  transformations?: string[]
  embed: boolean
  async_processing: boolean
  scope: 'personal' | 'project' | 'company'
}

interface ProcessingStepProps {
  control: Control<CreateSourceFormData>
  transformations: Transformation[]
  selectedTransformations: string[]
  onToggleTransformation: (transformationId: string) => void
  loading?: boolean
  settings?: SettingsResponse
}

export function ProcessingStep({
  control,
  transformations,
  selectedTransformations,
  onToggleTransformation,
  loading = false,
  settings
}: ProcessingStepProps) {
  const { t } = useTranslation()
  const transformationItems = transformations.map((transformation) => ({
    id: transformation.id,
    title: transformation.title,
    description: transformation.description
  }))

  return (
    <div className="space-y-8">
      <FormSection
        title={`${t('navigation.transformations')} (${t('common.optional')})`}
        description={t('sources.processDescription')}
      >
        <CheckboxList
          items={transformationItems}
          selectedIds={selectedTransformations}
          onToggle={onToggleTransformation}
          loading={loading}
          emptyMessage={t('common.noMatches')}
        />
      </FormSection>

      <FormSection title={t('sources.visibility')} description={t('sources.visibilityLabel')}>
        <Controller
          control={control}
          name="scope"
          render={({ field }) => (
            <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label={t('sources.visibilityLabel')}>
              {(['personal', 'project', 'company'] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={field.value === value}
                  onClick={() => field.onChange(value)}
                  className={cn(
                    'flex flex-col items-start gap-1 rounded-md border p-3 text-left transition-colors',
                    field.value === value ? 'border-primary bg-primary/5' : 'border-input hover:bg-muted',
                  )}
                >
                  <span className="flex items-center gap-2 text-sm font-medium">
                    {value === 'personal' && <Lock className="h-4 w-4" />}
                    {value === 'project' && <Users className="h-4 w-4" />}
                    {value === 'company' && <Building2 className="h-4 w-4" />}
                    {value === 'personal' && t('sources.visibilityPersonal')}
                    {value === 'project' && t('sources.visibilityProject')}
                    {value === 'company' && t('sources.visibilityCompany')}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {value === 'personal' && t('sources.visibilityPersonalDesc')}
                    {value === 'project' && t('sources.visibilityProjectDesc')}
                    {value === 'company' && t('sources.visibilityCompanyDesc')}
                  </span>
                </button>
              ))}
            </div>
          )}
        />
      </FormSection>

      <FormSection
        title={t('navigation.settings')}
        description={t('sources.processDescription')}
      >
        <div className="space-y-4">
          {settings?.default_embedding_option === 'ask' && (
            <Controller
              control={control}
              name="embed"
              render={({ field }) => (
                <label 
                  htmlFor="enable-embedding"
                  className="flex items-start gap-3 cursor-pointer p-3 rounded-md hover:bg-muted"
                >
                  <Checkbox
                    id="enable-embedding"
                    checked={field.value}
                    onCheckedChange={field.onChange}
                    className="mt-0.5"
                  />
                  <div className="flex-1">
                    <span className="text-sm font-medium block">{t('sources.enableEmbedding')}</span>
                    <p className="text-xs text-muted-foreground mt-1">
                      {t('sources.embeddingDesc')}
                    </p>
                  </div>
                </label>
              )}
            />
          )}

          {settings?.default_embedding_option === 'always' && (
            <div className="p-3 rounded-md bg-primary/10 border border-primary/30">
              <div className="flex items-start gap-3">
                <div className="w-4 h-4 bg-primary rounded-full mt-0.5 flex-shrink-0"></div>
                <div className="flex-1">
                  <span className="text-sm font-medium block text-primary">{t('sources.embeddingAlways')}</span>
                  <p className="text-xs text-primary mt-1">
                    {t('sources.embeddingAlwaysDesc')}
                    {t('sources.changeInSettings')} <span className="font-medium">{t('navigation.settings')}</span>.
                  </p>
                </div>
              </div>
            </div>
          )}

          {settings?.default_embedding_option === 'never' && (
            <div className="p-3 rounded-md bg-muted border border-border">
              <div className="flex items-start gap-3">
                <div className="w-4 h-4 bg-muted-foreground rounded-full mt-0.5 flex-shrink-0"></div>
                <div className="flex-1">
                  <span className="text-sm font-medium block text-foreground">{t('sources.embeddingNever')}</span>
                  <p className="text-xs text-muted-foreground mt-1">
                    {t('sources.embeddingNeverDesc')}
                    {t('sources.changeInSettings')} <span className="font-medium">{t('navigation.settings')}</span>.
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      </FormSection>
    </div>
  )
}
