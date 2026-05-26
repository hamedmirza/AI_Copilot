import { useEffect, useMemo, useRef } from 'react'
import type { ChatMessage, ChatToolCall } from '@/store'
import { EmptyState, Skeleton } from '@/components/ui/primitives'
import { MessageBubble } from './MessageBubble'
import { ToolCallCard } from './ToolCallCard'
import { prepareMessagesForDisplay } from './types'

interface MessageListProps {
  messages: ChatMessage[]
  loading?: boolean
  streaming?: boolean
  thinkingLabel?: string | null
  pendingToolCalls?: ChatToolCall[]
  onOpenRunInAgents?: (runId: string) => void
}

export function MessageList({
  messages,
  loading,
  streaming,
  thinkingLabel,
  pendingToolCalls = [],
  onOpenRunInAgents,
}: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const displayMessages = useMemo(() => prepareMessagesForDisplay(messages), [messages])

  useEffect(() => {
    const element = scrollRef.current
    if (!element) return
    element.scrollTop = element.scrollHeight
  }, [displayMessages, pendingToolCalls, streaming])

  if (loading) {
    return (
      <div className="flex-1 overflow-auto p-3 space-y-3">
        {[1, 2, 3].map((item) => (
          <Skeleton key={item} className="h-20 w-full" />
        ))}
      </div>
    )
  }

  if (displayMessages.length === 0 && pendingToolCalls.length === 0) {
    return (
      <div className="flex-1 overflow-hidden">
        <EmptyState
          title="Start a chat"
          description="Ask about the project, switch modes, or run /task to launch the pipeline."
        />
      </div>
    )
  }

  return (
    <div ref={scrollRef} className="flex-1 overflow-auto p-3 space-y-3">
      {displayMessages.map((message) => (
        <MessageBubble
          key={message.id}
          message={message}
          thinkingLabel={message.pending ? thinkingLabel : null}
          onOpenRunInAgents={onOpenRunInAgents}
        />
      ))}
      {pendingToolCalls.length > 0 && (
        <div className="space-y-2">
          {pendingToolCalls.map((toolCall) => (
            <ToolCallCard key={toolCall.id} toolCall={toolCall} />
          ))}
        </div>
      )}
    </div>
  )
}
