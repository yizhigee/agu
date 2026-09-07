/**
 * notes 模块首页 — M1 列表 + 录入/编辑/删除。
 */
import { useCallback, useEffect, useState } from 'react'
import { Pencil, Plus, Search, Trash2 } from 'lucide-react'
import { PageHeader } from '@/components/PageHeader'
import { toast } from '@/components/Toast'
import { cn } from '@/lib/cn'
import { notesApi, type Note, type NoteType } from '../lib/api'
import { NoteEditorDialog } from '../components/NoteEditorDialog'
import { DeleteNoteDialog } from '../components/DeleteNoteDialog'

const TYPE_FILTERS: { value: NoteType | 'all'; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'idea', label: '💡 想法' },
  { value: 'knowledge', label: '📚 新知识' },
  { value: 'pitfall', label: '💣 踩坑' },
  { value: 'review', label: '📊 复盘' },
  { value: 'question', label: '❓ 疑问' },
]

function formatTime(iso: string): string {
  // 显示本地时区简写日期
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${y}-${m}-${day} ${hh}:${mm}`
}

export function NoteHomePage() {
  const [notes, setNotes] = useState<Note[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState<NoteType | 'all'>('all')
  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState<Note | undefined>(undefined)
  const [deleting, setDeleting] = useState<Note | null>(null)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const res = await notesApi.listNotes({
        type: typeFilter === 'all' ? undefined : typeFilter,
        search: search.trim() || undefined,
      })
      setNotes(res.items)
    } catch (e) {
      toast(`加载笔记失败:${e}`, 'error')
    } finally {
      setLoading(false)
    }
  }, [typeFilter, search])

  useEffect(() => {
    void reload()
  }, [reload])

  function openCreate() {
    setEditing(undefined)
    setEditorOpen(true)
  }

  function openEdit(note: Note) {
    setEditing(note)
    setEditorOpen(true)
  }

  async function confirmDelete(hard: boolean) {
    if (!deleting) return
    try {
      await notesApi.deleteNote(deleting.id, hard)
      toast(hard ? '已彻底删除' : '已删除(30 天内可恢复)', 'success')
      setDeleting(null)
      void reload()
    } catch (e) {
      toast(`删除失败:${e}`, 'error')
    }
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <PageHeader
        title="笔记"
        subtitle="碎片记录与知识关联(M1:CRUD)"
        right={
          <button
            type="button"
            onClick={openCreate}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-btn text-sm bg-primary text-primary-foreground hover:bg-primary/90"
          >
            <Plus className="h-4 w-4" />
            新建
          </button>
        }
      />

      {/* 搜索 + 类型过滤 */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索笔记…"
            className="w-full rounded-btn bg-elevated border border-border pl-8 pr-3 py-1.5 text-sm text-foreground placeholder:text-muted focus:outline-none focus:border-primary/50"
          />
        </div>
        <div className="flex flex-wrap gap-1.5">
          {TYPE_FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              onClick={() => setTypeFilter(f.value)}
              className={cn(
                'px-2.5 py-1 rounded-full text-xs transition-colors',
                typeFilter === f.value
                  ? 'bg-primary/20 text-primary border border-primary/40'
                  : 'bg-elevated text-secondary border border-border hover:text-foreground',
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* 列表 */}
      <div className="rounded-card border border-border bg-elevated">
        {loading ? (
          <div className="p-6 text-sm text-muted">加载中…</div>
        ) : notes.length === 0 ? (
          <div className="p-6 text-sm text-muted">还没有笔记,点右上角"新建"开始记录 ✏️</div>
        ) : (
          <ul className="divide-y divide-border">
            {notes.map((note) => (
              <li key={note.id} className="p-3 flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 text-xs text-muted">
                    <span>{formatTime(note.created_at)}</span>
                    {note.pinned && (
                      <span className="text-amber-300" title="已置顶">📌</span>
                    )}
                    {note.tags.length > 0 && (
                      <span className="text-secondary truncate">
                        {note.tags.map((t) => `#${t}`).join(' ')}
                      </span>
                    )}
                  </div>
                  {note.title && (
                    <h3 className="mt-1 text-sm font-medium text-foreground">{note.title}</h3>
                  )}
                  <p className="mt-1 text-sm text-secondary line-clamp-3 whitespace-pre-wrap">
                    {note.content}
                  </p>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    type="button"
                    onClick={() => openEdit(note)}
                    title="编辑"
                    className="p-1.5 rounded-btn text-muted hover:text-foreground hover:bg-surface"
                  >
                    <Pencil className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => setDeleting(note)}
                    title="删除"
                    className="p-1.5 rounded-btn text-muted hover:text-rose-300 hover:bg-surface"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <NoteEditorDialog
        open={editorOpen}
        mode={editing ? 'edit' : 'create'}
        initial={editing}
        onClose={() => setEditorOpen(false)}
        onSaved={() => {
          void reload()
        }}
      />

      {deleting && (
        <DeleteNoteDialog
          noteId={deleting.id}
          notePreview={deleting.title || deleting.content.slice(0, 80)}
          onClose={() => setDeleting(null)}
          onConfirm={confirmDelete}
        />
      )}
    </div>
  )
}

export default NoteHomePage