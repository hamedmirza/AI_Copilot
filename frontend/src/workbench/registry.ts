import type { LucideIcon } from 'lucide-react'
import type { ComponentType } from 'react'

export type WorkbenchZone = 'sidebar' | 'center' | 'right' | 'bottom'

export interface WorkbenchContribution {
  id: string
  zone: WorkbenchZone
  title: string
  icon: LucideIcon
  order?: number
  Component: ComponentType
}

const contributions: WorkbenchContribution[] = []

export function registerContribution(c: WorkbenchContribution): void {
  if (contributions.some((x) => x.id === c.id && x.zone === c.zone)) {
    throw new Error(`Duplicate workbench contribution: ${c.zone}/${c.id}`)
  }
  contributions.push(c)
}

export function getContributions(zone: WorkbenchZone): WorkbenchContribution[] {
  return contributions
    .filter((c) => c.zone === zone)
    .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
}

export function getContribution(zone: WorkbenchZone, id: string): WorkbenchContribution | undefined {
  return contributions.find((c) => c.zone === zone && c.id === id)
}
