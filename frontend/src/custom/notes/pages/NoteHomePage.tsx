/**
 * notes 模块首页 — M0 骨架占位页。
 *
 * 调用 `/api/custom/notes/health` 展示模块状态,验证前后端打通。
 * M1 起替换为真实笔记列表页。
 */
import { useEffect, useState } from 'react'
import { PageHeader } from '@/components/PageHeader'
import { notesApi, type NotesHealth } from '../lib/api'

function StatusBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs ' +
        (ok
          ? 'bg-emerald-500/10 text-emerald-300'
          : 'bg-amber-500/10 text-amber-300')
      }
    >
      <span className={ok ? 'h-1.5 w-1.5 rounded-full bg-emerald-400' : 'h-1.5 w-1.5 rounded-full bg-amber-400'} />
      {label}
    </span>
  )
}

export function NoteHomePage() {
  const [health, setHealth] = useState<NotesHealth | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    notesApi
      .health()
      .then((h) => {
        if (!cancelled) setHealth(h)
      })
      .catch((e) => {
        if (!cancelled) setError(String(e))
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="flex flex-col gap-4 p-4">
      <PageHeader
        title="笔记"
        subtitle="碎片记录与知识关联模块(M0 骨架)"
      />
      <div className="rounded-card border border-border bg-elevated p-6">
        <div className="flex items-center gap-2">
          <span className="text-base text-foreground">模块已就绪 ✅</span>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {health ? (
            <>
              <StatusBadge ok={health.status === 'ok'} label={`status: ${health.status}`} />
              <StatusBadge ok={health.schema_version >= 1} label={`schema v${health.schema_version}`} />
              <StatusBadge ok={health.ai_key} label="AI Key" />
              <StatusBadge ok={false} label="DB (M1 接入)" />
            </>
          ) : error ? (
            <span className="text-sm text-rose-300">健康检查失败:{error}</span>
          ) : (
            <span className="text-sm text-muted">加载中…</span>
          )}
        </div>
        <p className="mt-4 text-sm text-muted">
          本页为 M0 骨架占位,后续阶段将逐步接入:CRUD(M1)→ AI 标签建议(M2)→
          模式检测与规则提炼(M3)→ 对话与知识图谱(M4)。
        </p>
      </div>
    </div>
  )
}

export default NoteHomePage