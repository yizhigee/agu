/**
 * 笔记录入/编辑弹窗。
 *
 * - mode=create:空表单,提交后创建
 * - mode=edit:预填现有笔记,提交后更新
 */
import { useEffect, useRef, useState } from 'react'
import { Modal } from '@/components/Modal'
import { notesApi, type Note, type NoteType, type NoteCreatePayload, type NoteUpdatePayload } from '../lib/api'

const TYPE_OPTIONS: { value: NoteType; label: string; hint: string }[] = [
  { value: 'idea', label: '💡 想法', hint: '灵感/猜想' },
  { value: 'knowledge', label: '📚 新知识', hint: '从外部学到的' },
  { value: 'pitfall', label: '💣 踩坑', hint: '自己亏过/做错的' },
  { value: 'review', label: '📊 复盘', hint: '事后分析' },
  { value: 'question', label: '❓ 疑问', hint: '还没想清楚' },
]

export interface NoteEditorDialogProps {
  open: boolean
  mode: 'create' | 'edit'
  initial?: Note
  onClose: () => void
  onSaved: (note: Note) => void
}

export function NoteEditorDialog({ open, mode, initial, onClose, onSaved }: NoteEditorDialogProps) {
  const [type, setType] = useState<NoteType>(initial?.type ?? 'idea')
  const [title, setTitle] = useState(initial?.title ?? '')
  const [content, setContent] = useState(initial?.content ?? '')
  const [tagsRaw, setTagsRaw] = useState((initial?.tags ?? []).join(', '))
  const [pinned, setPinned] = useState(initial?.pinned ?? false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const contentRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (open) {
      setType(initial?.type ?? 'idea')
      setTitle(initial?.title ?? '')
      setContent(initial?.content ?? '')
      setTagsRaw((initial?.tags ?? []).join(', '))
      setPinned(initial?.pinned ?? false)
      setError(null)
      setSubmitting(false)
    }
  }, [open, initial])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!content.trim()) {
      setError('内容不能为空')
      return
    }
    setSubmitting(true)
    setError(null)
    const tags = tagsRaw
      .split(/[,，\s]+/)
      .map((t) => t.trim())
      .filter(Boolean)
    try {
      let saved: Note
      if (mode === 'create') {
        const payload: NoteCreatePayload = { type, content, tags, pinned }
        if (title.trim()) payload.title = title.trim()
        saved = await notesApi.createNote(payload)
      } else {
        if (!initial) throw new Error('edit mode requires initial note')
        const payload: NoteUpdatePayload = { type, content, tags, pinned }
        if (title.trim()) payload.title = title.trim()
        saved = await notesApi.updateNote(initial.id, payload)
      }
      onSaved(saved)
      onClose()
    } catch (e) {
      setError(String(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      onClose={onClose}
      labelledBy="note-editor-title"
      panelClassName="w-[92vw] max-w-2xl bg-surface border border-border rounded-card shadow-xl"
    >
      <form onSubmit={handleSubmit} className="flex flex-col gap-3 p-5">
        <h2 id="note-editor-title" className="text-base font-medium text-foreground">
          {mode === 'create' ? '新建笔记' : '编辑笔记'}
        </h2>

        {/* 类型 */}
        <div className="flex flex-wrap gap-1.5">
          {TYPE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              title={opt.hint}
              onClick={() => setType(opt.value)}
              className={
                'px-2.5 py-1 rounded-full text-xs transition-colors ' +
                (type === opt.value
                  ? 'bg-primary/20 text-primary border border-primary/40'
                  : 'bg-elevated text-secondary border border-border hover:text-foreground')
              }
            >
              {opt.label}
            </button>
          ))}
        </div>

        {/* 标题 */}
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="标题(可选,默认取首句)"
          className="w-full rounded-btn bg-elevated border border-border px-3 py-2 text-sm text-foreground placeholder:text-muted focus:outline-none focus:border-primary/50"
        />

        {/* 内容 */}
        <textarea
          ref={contentRef}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="写一句话记录一下…"
          rows={6}
          className="w-full rounded-btn bg-elevated border border-border px-3 py-2 text-sm text-foreground placeholder:text-muted focus:outline-none focus:border-primary/50 resize-y"
        />

        {/* 标签 */}
        <input
          type="text"
          value={tagsRaw}
          onChange={(e) => setTagsRaw(e.target.value)}
          placeholder="标签(逗号分隔,如:半导体, 光模块)"
          className="w-full rounded-btn bg-elevated border border-border px-3 py-2 text-sm text-foreground placeholder:text-muted focus:outline-none focus:border-primary/50"
        />

        {/* 置顶 */}
        <label className="flex items-center gap-2 text-sm text-secondary">
          <input
            type="checkbox"
            checked={pinned}
            onChange={(e) => setPinned(e.target.checked)}
            className="h-4 w-4 rounded border-border bg-elevated"
          />
          置顶
        </label>

        {error && <p className="text-sm text-rose-300">{error}</p>}

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="px-3 py-1.5 rounded-btn text-sm text-secondary hover:text-foreground hover:bg-elevated"
          >
            取消
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="px-3 py-1.5 rounded-btn text-sm bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {submitting ? '保存中…' : mode === 'create' ? '创建' : '保存'}
          </button>
        </div>
      </form>
    </Modal>
  )
}