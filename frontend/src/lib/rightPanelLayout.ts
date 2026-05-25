export type RightPanelTab = 'chat' | 'runs' | 'agents'

/** CSS classes for a right-panel tab pane (mounted but hidden when inactive). */
export function rightPanelPanelClass(active: boolean): string {
  return active ? 'flex h-full min-h-0 flex-col' : 'hidden'
}

export function isRightPanelTabMounted(tab: RightPanelTab, tabs: readonly RightPanelTab[]): boolean {
  return tabs.includes(tab)
}
