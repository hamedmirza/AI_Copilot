export const VALIDATION_PROFILES = [
  { value: 'python', label: 'Python' },
  { value: 'react', label: 'React' },
  { value: 'fullstack', label: 'Fullstack' },
  { value: 'node', label: 'Node' },
  { value: 'custom', label: 'Custom' },
] as const

export type SourceType = 'workspace' | 'git'

export interface ProjectWizardForm {
  name: string
  description: string
  source_type: SourceType
  source_repo_spec: string
  validation_profile: string
}

export const emptyWizardForm = (): ProjectWizardForm => ({
  name: '',
  description: '',
  source_type: 'workspace',
  source_repo_spec: '',
  validation_profile: 'python',
})
