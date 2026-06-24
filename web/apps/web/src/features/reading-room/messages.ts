import type { UIMessage } from 'ai'

export type MessagePart = UIMessage['parts'][number] & Record<string, unknown>

export type ToolPart = MessagePart & {
  type: `tool-${string}` | 'dynamic-tool'
  state: string
  toolCallId: string
  input?: unknown
  output?: unknown
  errorText?: string
  approval?: { id: string; approved?: boolean; reason?: string }
}

export function isToolPart(part: MessagePart): part is ToolPart {
  return typeof part.type === 'string' && (part.type.startsWith('tool-') || part.type === 'dynamic-tool')
}

export function messageText(message: UIMessage): string {
  return message.parts
    .filter((part) => part.type === 'text')
    .map((part) => String((part as MessagePart).text || ''))
    .join('\n')
    .trim()
}

export function assistantText(message: UIMessage | null): string {
  if (!message) return ''
  return messageText(message).replace(/\s+/g, ' ')
}
