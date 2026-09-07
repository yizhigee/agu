/**
 * 删除笔记确认弹窗(软删优先,可勾选"彻底删除")。
 */
import { useState } from 'react'
import { Modal } from '@/components/Modal'

export interface DeleteNoteDialogProps {
  noteId: string
  notePreview: string
  onClose: () => void
  onConfirm: (hard: boolean) => Promise<void> | void
}

export function DeleteNoteDialog({ noteId, notePreview, onClose, onConfirm }: DeleteNoteDialogProps) {
  const [hard, setHard] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleConfirm() {
    setSubmitting(true)
    setError(null)
    try {
      await onConfirm(hard)
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
      labelledBy="delete-note-title"
      panelClassName="w-[92vw] max-w-md bg-surface border border-border rounded-card shadow-xl"
    >
      <div className="flex flex-col gap-3 p-5">
        <h2 id="delete-note-title" className="text-base font-medium text-foreground">
          删除笔记?
        </h2>
        <p className="text-sm text-secondary">
          <span className="text-muted">id:</span> <code className="text-xs">{noteId.slice(0, 8)}…</code>
        </p>
        {notePreview && (
          <div className="rounded-btn bg-elevated px-3 py-2 text-sm text-foreground line-clamp-3">
            {notePreview}
          </div>
        )}
        <label className="flex items-center gap-2 text-sm text-secondary">
          <input
            type="checkbox"
            checked={hard}
            onChange={(e) => setHard(e.target.checked)}
            className="h-4 w-4 rounded border-border bg-elevated"
          />
          彻底删除(默认软删,30 天内可恢复)
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
            type="button"
            onClick={handleConfirm}
            disabled={submitting}
            className="px-3 py-1.5 rounded-btn text-sm bg-rose-500/90 text-white hover:bg-rose-500 disabled:opacity-50"
          >
            {submitting ? '删除中…' : hard ? '彻底删除' : '删除(软删)'}
          </button>
        </div>
      </div>
    </Modal>
  )
}