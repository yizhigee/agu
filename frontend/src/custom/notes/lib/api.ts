/**
 * notes 模块 — 前端 API 客户端。
 *
 * 严格限定在本模块 lib/ 内,不污染核心 @/lib/api.ts。
 * 端点均以 /api/custom/notes/* 为前缀。
 */
import { ApiError } from '@/lib/api'

export interface NotesHealth {
  status: 'ok' | string
  module: string
  schema_version: number
  db: boolean
  ai_key: boolean
}

export interface NotesSchemaVersion {
  version: number
  migrations: unknown[]
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!response.ok) {
    throw new ApiError(`notes API ${path} failed: ${response.status}`, response.status)
  }
  return (await response.json()) as T
}

export const notesApi = {
  health(): Promise<NotesHealth> {
    return request<NotesHealth>('/api/custom/notes/health')
  },
  schemaVersion(): Promise<NotesSchemaVersion> {
    return request<NotesSchemaVersion>('/api/custom/notes/schema-version')
  },
}