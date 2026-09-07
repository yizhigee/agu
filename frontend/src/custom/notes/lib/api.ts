/**
 * notes 模块 — 前端 API 客户端(M1 CRUD)。
 */
import { ApiError } from '@/lib/api'

export type NoteType = 'knowledge' | 'pitfall' | 'review' | 'idea' | 'question'

export interface Note {
  id: string
  type: NoteType
  title: string | null
  content: string
  tags: string[]
  related_stocks: string[]
  source_url: string | null
  source_app: string | null
  mood: string | null
  pnl: number | null
  read_status: string
  next_review_at: string | null
  pinned: boolean
  created_at: string
  updated_at: string
  deleted_at: string | null
  tag_ids?: string[]
}

export interface Tag {
  id: string
  name: string
  color: string | null
  use_count: number
}

export interface NotesHealth {
  status: string
  module: string
  schema_version: number
  db: boolean
  ai_key: boolean
}

export interface NotesSchemaVersion {
  version: number
  migrations: unknown[]
}

export interface NoteCreatePayload {
  type: NoteType
  content: string
  title?: string
  tags?: string[]
  related_stocks?: string[]
  pinned?: boolean
}

export interface NoteUpdatePayload {
  title?: string
  content?: string
  tags?: string[]
  pinned?: boolean
  type?: NoteType
}

export interface TagSuggestion {
  name: string
  confidence: number
  reason?: string
}

export interface SuggestTagsResponse {
  suggested_type?: NoteType | null
  suggested_type_confidence?: number | null
  tags: TagSuggestion[]
  model?: string
  latency_ms: number
}

export interface DetectedPattern {
  cluster_key: string
  type: NoteType
  tag: string | null
  note_count: number
  sample_note_ids: string[]
  sample_titles: string[]
  sample_total: number
}

export interface DetectPatternsResponse {
  patterns: DetectedPattern[]
  total_notes_scanned: number
}

export interface Rule {
  id: string
  category: string
  title: string
  trigger_conditions: string[]
  exceptions: string | null
  source_note_ids: string[]
  status: 'active' | 'draft' | 'archived'
  violation_count: number
  last_violated_at: string | null
  created_at: string
  updated_at: string
}

export interface RuleCreatePayload {
  category: string
  title: string
  trigger_conditions?: string[]
  exceptions?: string | null
  source_note_ids?: string[]
  status?: 'active' | 'draft' | 'archived'
}

export interface RuleUpdatePayload {
  title?: string
  category?: string
  trigger_conditions?: string[]
  exceptions?: string | null
  status?: 'active' | 'draft' | 'archived'
}

export interface DraftRuleResponse {
  category: string
  title: string
  trigger_conditions: string[]
  exceptions: string | null
  rationale: string
  model?: string
  latency_ms: number
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!response.ok) {
    const text = await response.text().catch(() => '')
    throw new ApiError(`notes API ${path} failed: ${response.status} ${text}`, response.status)
  }
  return (await response.json()) as T
}

async function requestVoid(path: string, init?: RequestInit): Promise<void> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!response.ok) {
    const text = await response.text().catch(() => '')
    throw new ApiError(`notes API ${path} failed: ${response.status} ${text}`, response.status)
  }
}

export const notesApi = {
  health(): Promise<NotesHealth> {
    return request<NotesHealth>('/api/custom/notes/health')
  },
  schemaVersion(): Promise<NotesSchemaVersion> {
    return request<NotesSchemaVersion>('/api/custom/notes/schema-version')
  },

  // Notes
  listNotes(params?: {
    type?: NoteType
    search?: string
    pinned_only?: boolean
  }): Promise<{ items: Note[]; count: number }> {
    const qs = new URLSearchParams()
    if (params?.type) qs.set('type', params.type)
    if (params?.search) qs.set('search', params.search)
    if (params?.pinned_only) qs.set('pinned_only', 'true')
    const suffix = qs.toString() ? `?${qs.toString()}` : ''
    return request<{ items: Note[]; count: number }>(`/api/custom/notes/notes${suffix}`)
  },
  getNote(id: string): Promise<Note> {
    return request<Note>(`/api/custom/notes/notes/${id}`)
  },
  createNote(payload: NoteCreatePayload): Promise<Note> {
    return request<Note>('/api/custom/notes/notes', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  updateNote(id: string, payload: NoteUpdatePayload): Promise<Note> {
    return request<Note>(`/api/custom/notes/notes/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
  },
  deleteNote(id: string, hard = false): Promise<{ deleted: boolean; hard: boolean; id: string }> {
    const suffix = hard ? '?hard=true' : ''
    return requestVoid(`/api/custom/notes/notes/${id}${suffix}`, { method: 'DELETE' })
      .then(() => ({ deleted: true, hard, id }))
  },

  // Tags
  listTags(): Promise<{ items: Tag[]; count: number }> {
    return request<{ items: Tag[]; count: number }>('/api/custom/notes/tags')
  },

  // AI
  suggestTags(payload: {
    title?: string
    content: string
    existing_tags?: string[]
    max_suggest?: number
  }): Promise<SuggestTagsResponse> {
    return request<SuggestTagsResponse>('/api/custom/notes/ai/suggest-tags', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  // Patterns (M3)
  detectPatterns(params?: { min_count?: number; limit?: number }): Promise<DetectPatternsResponse> {
    const qs = new URLSearchParams()
    if (params?.min_count) qs.set('min_count', String(params.min_count))
    if (params?.limit) qs.set('limit', String(params.limit))
    const suffix = qs.toString() ? `?${qs.toString()}` : ''
    return request<DetectPatternsResponse>(`/api/custom/notes/patterns/detect${suffix}`)
  },

  // Rules (M3)
  listRules(params?: { status?: 'active' | 'draft' | 'archived' }): Promise<{ items: Rule[]; count: number }> {
    const qs = params?.status ? `?status=${params.status}` : ''
    return request<{ items: Rule[]; count: number }>(`/api/custom/notes/rules${qs}`)
  },
  createRule(payload: RuleCreatePayload): Promise<Rule> {
    return request<Rule>('/api/custom/notes/rules', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  updateRule(id: string, payload: RuleUpdatePayload): Promise<Rule> {
    return request<Rule>(`/api/custom/notes/rules/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
  },
  deleteRule(id: string): Promise<void> {
    return requestVoid(`/api/custom/notes/rules/${id}`, { method: 'DELETE' })
  },

  // AI draft rule
  draftRule(payload: {
    note_ids: string[]
    category_hint?: string
    type_hint?: string
  }): Promise<DraftRuleResponse> {
    return request<DraftRuleResponse>('/api/custom/notes/ai/draft-rule', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
}