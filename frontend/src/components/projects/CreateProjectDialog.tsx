'use client'

import { useEffect } from 'react'
import { useForm, Controller } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useCreateProject } from '@/lib/hooks/use-projects'
import { useTranslation } from '@/lib/hooks/use-translation'

const createProjectSchema = z.object({
  name: z.string().min(1, 'Name is required'),
  description: z.string().optional(),
  defaultSourceScope: z.enum(['personal', 'project', 'company']),
})

type CreateProjectFormData = z.infer<typeof createProjectSchema>

interface CreateProjectDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function CreateProjectDialog({ open, onOpenChange }: CreateProjectDialogProps) {
  const { t } = useTranslation()
  const createProject = useCreateProject()
  const {
    register,
    handleSubmit,
    control,
    formState: { errors, isValid },
    reset,
  } = useForm<CreateProjectFormData>({
    resolver: zodResolver(createProjectSchema),
    mode: 'onChange',
    defaultValues: {
      name: '',
      description: '',
      defaultSourceScope: 'personal',
    },
  })

  const closeDialog = () => onOpenChange(false)

  const onSubmit = async (data: CreateProjectFormData) => {
    await createProject.mutateAsync({
      name: data.name,
      description: data.description,
      default_source_scope: data.defaultSourceScope,
    })
    closeDialog()
    reset()
  }

  useEffect(() => {
    if (!open) {
      reset()
    }
  }, [open, reset])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>{t('projects.createNew')}</DialogTitle>
          <DialogDescription>
            {t('projects.createNewDesc')}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="project-name">{t('common.name')} *</Label>
            <Input
              id="project-name"
              {...register('name')}
              placeholder={t('projects.namePlaceholder')}
              autoComplete="off"
            />
            {errors.name && (
              <p className="text-sm text-destructive">{errors.name.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="project-description">{t('common.description')}</Label>
            <Textarea
              id="project-description"
              {...register('description')}
              placeholder={t('projects.descPlaceholder')}
              rows={4}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="project-default-source-scope">
              {t('projects.defaultSourceScope.label')}
            </Label>
            <Controller
              control={control}
              name="defaultSourceScope"
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger id="project-default-source-scope">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="personal">
                      {t('projects.defaultSourceScope.personal')}
                    </SelectItem>
                    <SelectItem value="project">
                      {t('projects.defaultSourceScope.project')}
                    </SelectItem>
                    <SelectItem value="company">
                      {t('projects.defaultSourceScope.company')}
                    </SelectItem>
                  </SelectContent>
                </Select>
              )}
            />
          </div>

          <DialogFooter className="gap-2 sm:gap-0">
            <Button type="button" variant="outline" onClick={closeDialog}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={!isValid || createProject.isPending}>
              {createProject.isPending ? t('common.creating') : t('projects.createNew')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
