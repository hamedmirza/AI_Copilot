import { useState } from 'react'
import { useUIStore } from '@/store'

export function ClarificationDrawerPage() {
  const [isOpen, setIsOpen] = useState(true)
  const { activePanel } = useUIStore()

  return (
    <div className="flex h-full w-full flex-col">
      <header className="border-b px-4 py-2">
        <h1 className="text-lg font-semibold">Clarification Drawer</h1>
      </header>
      <main className="flex-1 overflow-auto p-4">
        <div className="max-w-2xl space-y-4">
          <p>This is the Clarification Drawer page component.</p>
          <button 
            onClick={() => setIsOpen(!isOpen)}
            className="rounded bg-blue-500 px-4 py-2 text-white hover:bg-blue-600"
          >
            {isOpen ? 'Close Drawer' : 'Open Drawer'}
          </button>
        </div>
      </main>
    </div>
  )
}