/**
 * notes 模块首页 — M1 列表 + M3 模式/规则 tab。
 */
import { useCallback, useEffect, useState } from 'react'
import {
  Archive,
  ArchiveRestore,
  Pencil,
  Plus,
  RotateCcw,
  Search,
  Sparkles,
  Trash2,
} from 'lucide-react'
import { PageHeader } from '@/components/PageHeader'
import { toast } from '@/components/Toast'
import { cn } from '@/lib/cn'
import { notesApi, type Note, type NoteType, type DetectedPattern, type Rule } from '../lib/api'
import { NoteEditorDialog } from '../components/NoteEditorDialog'
import { DeleteNoteDialog } from '../components/DeleteNoteDialog'
import { RuleDraftDialog } from '../components/RuleDraftDialog'

const TYPE_FILTERS: { value: NoteType | 'all'; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'idea', label: '💡 想法' },
  { value: 'knowledge', label: '📚 新知识' },
  { value: 'pitfall', label: '💣 踩坑' },
  { value: 'review', label: '📊 复盘' },
  { value: 'question', label: '❓ 疑问' },
]

type Tab = 'notes' | 'patterns' | 'rules' | 'trash'

function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${y}-${m}-${day} ${hh}:${mm}`
}

const TYPE_LABEL: Record<NoteType, string> = {
  idea: '💡 想法',
  knowledge: '📚 新知识',
  pitfall: '💣 踩坑',
  review: '📊 复盘',
  question: '❓ 疑问',
}

export function NoteHomePage() {
  const [tab, setTab] = useState<Tab>('notes')

  // ---- Notes state ----
  const [notes, setNotes] = useState<Note[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState<NoteType | 'all'>('all')
  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState<Note | undefined>(undefined)
  const [deleting, setDeleting] = useState<Note | null>(null)

  // ---- Patterns state ----
  const [patterns, setPatterns] = useState<DetectedPattern[]>([])
  const [patternsLoading, setPatternsLoading] = useState(false)
  const [minCount, setMinCount] = useState(3)
  const [drafting, setDrafting] = useState<DetectedPattern | null>(null)

  // ---- Rules state ----
  const [rules, setRules] = useState<Rule[]>([])
  const [rulesLoading, setRulesLoading] = useState(false)
  const [ruleFilter, setRuleFilter] = useState<'active' | 'all' | 'archived'>('active')

  // ---- Trash state ----
  const [trashNotes, setTrashNotes] = useState<Note[]>([])
  const [trashLoading, setTrashLoading] = useState(false)

  // ---- Reloads ----
  const reloadNotes = useCallback(async () => {
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

  const reloadPatterns = useCallback(async () => {
    setPatternsLoading(true)
    try {
      const res = await notesApi.detectPatterns({ min_count: minCount, limit: 12 })
      setPatterns(res.patterns)
    } catch (e) {
      toast(`加载模式失败:${e}`, 'error')
    } finally {
      setPatternsLoading(false)
    }
  }, [minCount])

  const reloadRules = useCallback(async () => {
    setRulesLoading(true)
    try {
      const res = await notesApi.listRules(
        ruleFilter === 'all' ? undefined : { status: ruleFilter },
      )
      setRules(res.items)
    } catch (e) {
      toast(`加载规则失败:${e}`, 'error')
    } finally {
      setRulesLoading(false)
    }
  }, [ruleFilter])

  const reloadTrash = useCallback(async () => {
    setTrashLoading(true)
    try {
      const res = await notesApi.listNotes({ deleted: true })
      setTrashNotes(res.items)
    } catch (e) {
      toast(`加载回收站失败:${e}`, 'error')
    } finally {
      setTrashLoading(false)
    }
  }, [])

  useEffect(() => {
    if (tab === 'notes') void reloadNotes()
    else if (tab === 'patterns') void reloadPatterns()
    else if (tab === 'rules') void reloadRules()
    else if (tab === 'trash') void reloadTrash()
  }, [tab, reloadNotes, reloadPatterns, reloadRules, reloadTrash])

  // ---- Handlers ----
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
      void reloadNotes()
    } catch (e) {
      toast(`删除失败:${e}`, 'error')
    }
  }

  async function adoptRule(rule: Rule) {
    toast(`已采纳规则:${rule.title}`, 'success')
    setTab('rules')
    setRuleFilter('active')
  }

  async function toggleRule(rule: Rule) {
    const newStatus = rule.status === 'active' ? 'archived' : 'active'
    try {
      await notesApi.updateRule(rule.id, { status: newStatus })
      void reloadRules()
    } catch (e) {
      toast(`更新失败:${e}`, 'error')
    }
  }

  async function removeRule(rule: Rule) {
    if (!confirm(`确定删除规则"${rule.title}"?`)) return
    try {
      await notesApi.deleteRule(rule.id)
      toast('已删除', 'success')
      void reloadRules()
    } catch (e) {
      toast(`删除失败:${e}`, 'error')
    }
  }

  async function restoreNote(note: Note) {
    try {
      await notesApi.restoreNote(note.id)
      toast('已恢复到笔记列表', 'success')
      void reloadTrash()
    } catch (e) {
      toast(`恢复失败:${e}`, 'error')
    }
  }

  async function purgeNote(note: Note) {
    const preview = note.title || note.content.slice(0, 30)
    if (!confirm(`彻底删除"${preview}"?\n此操作不可恢复。`)) return
    try {
      await notesApi.deleteNote(note.id, true)
      toast('已彻底删除', 'success')
      void reloadTrash()
    } catch (e) {
      toast(`删除失败:${e}`, 'error')
    }
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <PageHeader
        title="笔记"
        subtitle="碎片记录与知识关联"
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

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border">
        {(
          [
            { v: 'notes', label: '📝 笔记' },
            { v: 'patterns', label: '🔍 模式' },
            { v: 'rules', label: '🎯 我的规则' },
            { v: 'trash', label: '🗑️ 回收站' },
          ] as { v: Tab; label: string }[]
        ).map((t) => (
          <button
            key={t.v}
            type="button"
            onClick={() => setTab(t.v)}
            className={cn(
              'px-3 py-1.5 text-sm border-b-2 -mb-px transition-colors',
              tab === t.v
                ? 'border-primary text-primary'
                : 'border-transparent text-muted hover:text-foreground',
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ---- Notes tab ---- */}
      {tab === 'notes' && (
        <>
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

          <div className="rounded-card border border-border bg-elevated">
            {loading ? (
              <div className="p-6 text-sm text-muted">加载中…</div>
            ) : notes.length === 0 ? (
              <div className="p-6 text-sm text-muted">
                还没有笔记,点右上角"新建"开始记录 ✏️
              </div>
            ) : (
              <ul className="divide-y divide-border">
                {notes.map((note) => (
                  <li key={note.id} className="p-3 flex items-start gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 text-xs text-muted">
                        <span>{formatTime(note.created_at)}</span>
                        {note.pinned && <span className="text-amber-300" title="已置顶">📌</span>}
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
        </>
      )}

      {/* ---- Patterns tab ---- */}
      {tab === 'patterns' && (
        <>
          <div className="flex items-center gap-2 text-sm text-secondary">
            <label>
              最少笔记数:
              <input
                type="number"
                value={minCount}
                onChange={(e) => setMinCount(Math.max(2, Number(e.target.value) || 3))}
                min={2}
                className="ml-1 w-16 rounded-btn bg-elevated border border-border px-2 py-0.5 text-sm"
              />
            </label>
            <button
              type="button"
              onClick={() => void reloadPatterns()}
              className="px-2.5 py-1 rounded-btn text-xs bg-elevated text-secondary hover:text-foreground"
            >
              刷新
            </button>
            <span className="text-xs text-muted">
              反复出现的主题会被聚类,点击卡片让 AI 提炼为可执行规则
            </span>
          </div>

          <div className="rounded-card border border-border bg-elevated">
            {patternsLoading ? (
              <div className="p-6 text-sm text-muted">扫描中…</div>
            ) : patterns.length === 0 ? (
              <div className="p-6 text-sm text-muted">
                没有发现反复出现的主题(至少 {minCount} 条相同类型的笔记,可选共享同一 tag)
              </div>
            ) : (
              <ul className="divide-y divide-border">
                {patterns.map((p) => (
                  <li key={p.cluster_key} className="p-3 flex items-start gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 text-xs text-muted">
                        <span>{TYPE_LABEL[p.type] ?? p.type}</span>
                        {p.tag && (
                          <span className="rounded-full bg-primary/15 text-primary px-1.5 py-0.5">
                            #{p.tag}
                          </span>
                        )}
                        <span className="text-secondary">
                          {p.note_count} 条笔记
                          {p.sample_total > p.note_count ? ` (共 ${p.sample_total})` : ''}
                        </span>
                      </div>
                      <div className="mt-1 flex flex-wrap gap-1 text-xs text-secondary">
                        {p.sample_titles.slice(0, 3).map((t, i) => (
                          <span key={i} className="truncate max-w-[28ch]">
                            · {t}
                          </span>
                        ))}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => setDrafting(p)}
                      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-btn text-xs bg-primary/15 text-primary hover:bg-primary/25 shrink-0"
                    >
                      <Sparkles className="h-3.5 w-3.5" />
                      提炼为规则
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}

      {/* ---- Rules tab ---- */}
      {tab === 'rules' && (
        <>
          <div className="flex items-center gap-2">
            {(
              [
                { v: 'active', label: '启用' },
                { v: 'archived', label: '归档' },
                { v: 'all', label: '全部' },
              ] as { v: typeof ruleFilter; label: string }[]
            ).map((f) => (
              <button
                key={f.v}
                type="button"
                onClick={() => setRuleFilter(f.v)}
                className={cn(
                  'px-2.5 py-1 rounded-full text-xs transition-colors',
                  ruleFilter === f.v
                    ? 'bg-primary/20 text-primary border border-primary/40'
                    : 'bg-elevated text-secondary border border-border hover:text-foreground',
                )}
              >
                {f.label}
              </button>
            ))}
          </div>

          <div className="rounded-card border border-border bg-elevated">
            {rulesLoading ? (
              <div className="p-6 text-sm text-muted">加载中…</div>
            ) : rules.length === 0 ? (
              <div className="p-6 text-sm text-muted">
                还没有规则。回"模式"tab 让 AI 帮你提炼,或手动添加。
              </div>
            ) : (
              <ul className="divide-y divide-border">
                {rules.map((rule) => (
                  <li key={rule.id} className="p-3 flex items-start gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 text-xs text-muted">
                        <span className="rounded-full bg-primary/15 text-primary px-1.5 py-0.5">
                          {rule.category}
                        </span>
                        <span
                          className={cn(
                            'rounded-full px-1.5 py-0.5',
                            rule.status === 'active'
                              ? 'bg-emerald-400/15 text-emerald-300'
                              : rule.status === 'archived'
                                ? 'bg-muted/15 text-muted'
                                : 'bg-amber-400/15 text-amber-300',
                          )}
                        >
                          {rule.status === 'active' ? '启用中' : rule.status === 'archived' ? '已归档' : '草稿'}
                        </span>
                        <span>来源 {rule.source_note_ids.length} 条笔记</span>
                      </div>
                      <h3 className="mt-1 text-sm font-medium text-foreground">{rule.title}</h3>
                      <ul className="mt-1 text-xs text-secondary space-y-0.5">
                        {rule.trigger_conditions.map((t, i) => (
                          <li key={i}>· {t}</li>
                        ))}
                      </ul>
                      {rule.exceptions && (
                        <p className="mt-1 text-xs text-muted italic">例外:{rule.exceptions}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        type="button"
                        onClick={() => void toggleRule(rule)}
                        title={rule.status === 'active' ? '归档' : '启用'}
                        className="p-1.5 rounded-btn text-muted hover:text-foreground hover:bg-surface"
                      >
                        {rule.status === 'active' ? (
                          <Archive className="h-4 w-4" />
                        ) : (
                          <ArchiveRestore className="h-4 w-4" />
                        )}
                      </button>
                      <button
                        type="button"
                        onClick={() => void removeRule(rule)}
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
        </>
      )}

      {/* ---- Trash tab ---- */}
      {tab === 'trash' && (
        <>
          <div className="flex items-center gap-2 text-xs text-muted">
            <span>软删除的笔记会暂存在这里,可恢复或彻底清除。</span>
          </div>

          <div className="rounded-card border border-border bg-elevated">
            {trashLoading ? (
              <div className="p-6 text-sm text-muted">加载中…</div>
            ) : trashNotes.length === 0 ? (
              <div className="p-6 text-sm text-muted">回收站是空的 🎉</div>
            ) : (
              <ul className="divide-y divide-border">
                {trashNotes.map((note) => (
                  <li key={note.id} className="p-3 flex items-start gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 text-xs text-muted">
                        <span>删除于 {formatTime(note.deleted_at ?? '')}</span>
                        {note.tags.length > 0 && (
                          <span className="text-secondary truncate">
                            {note.tags.map((t) => `#${t}`).join(' ')}
                          </span>
                        )}
                      </div>
                      {note.title && (
                        <h3 className="mt-1 text-sm font-medium text-foreground line-through decoration-muted/50">
                          {note.title}
                        </h3>
                      )}
                      <p className="mt-1 text-sm text-secondary line-clamp-2 whitespace-pre-wrap">
                        {note.content}
                      </p>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        type="button"
                        onClick={() => void restoreNote(note)}
                        title="恢复"
                        className="p-1.5 rounded-btn text-muted hover:text-emerald-300 hover:bg-surface"
                      >
                        <RotateCcw className="h-4 w-4" />
                      </button>
                      <button
                        type="button"
                        onClick={() => void purgeNote(note)}
                        title="彻底删除(不可恢复)"
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
        </>
      )}

      {/* Dialogs */}
      <NoteEditorDialog
        open={editorOpen}
        mode={editing ? 'edit' : 'create'}
        initial={editing}
        onClose={() => setEditorOpen(false)}
        onSaved={() => {
          void reloadNotes()
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

      <RuleDraftDialog
        open={!!drafting}
        pattern={drafting}
        onClose={() => setDrafting(null)}
        onAdopted={(rule) => void adoptRule(rule)}
      />
    </div>
  )
}

export default NoteHomePage