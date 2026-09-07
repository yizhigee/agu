/**
 * AI 规则草稿对话框 — 显示 AI 提炼出的规则草稿,用户可编辑后采纳或丢弃。
 */
import { useEffect, useState } from 'react'
import { Modal } from '@/components/Modal'
import { Sparkles } from 'lucide-react'
import { notesApi, type DetectedPattern, type DraftRuleResponse, type Rule } from '../lib/api'

export interface RuleDraftDialogProps {
  open: boolean
  pattern: DetectedPattern | null
  onClose: () => void
  onAdopted: (rule: Rule) => void
}

export function RuleDraftDialog({ open, pattern, onClose, onAdopted }: RuleDraftDialogProps) {
  const [drafting, setDrafting] = useState(false)
  const [draft, setDraft] = useState<DraftRuleResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  // 编辑态字段
  const [title, setTitle] = useState('')
  const [category, setCategory] = useState('')
  const [triggers, setTriggers] = useState('')
  const [exceptions, setExceptions] = useState('')
  const [adopting, setAdopting] = useState(false)

  useEffect(() => {
    if (!open || !pattern) {
      setDraft(null)
      setError(null)
      return
    }
    setDrafting(true)
    setError(null)
    notesApi
      .draftRule({
        note_ids: pattern.sample_note_ids,
        category_hint: pattern.tag ?? undefined,
        type_hint: pattern.type,
      })
      .then((d) => {
        setDraft(d)
        setTitle(d.title)
        setCategory(d.category)
        setTriggers(d.trigger_conditions.join('\n'))
        setExceptions(d.exceptions ?? '')
      })
      .catch((e) => setError(String(e instanceof Error ? e.message : e)))
      .finally(() => setDrafting(false))
  }, [open, pattern])

  async function handleAdopt() {
    if (!pattern) return
    const triggerList = triggers
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean)
    if (!title.trim()) {
      setError('标题不能为空')
      return
    }
    if (triggerList.length === 0) {
      setError('至少要一条触发条件')
      return
    }
    setAdopting(true)
    setError(null)
    try {
      const rule = await notesApi.createRule({
        category: category.trim() || '复盘',
        title: title.trim(),
        trigger_conditions: triggerList,
        exceptions: exceptions.trim() || null,
        source_note_ids: pattern.sample_note_ids,
      })
      onAdopted(rule)
      onClose()
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e))
    } finally {
      setAdopting(false)
    }
  }

  return (
    <Modal
      onClose={onClose}
      labelledBy="rule-draft-title"
      panelClassName="w-[92vw] max-w-2xl bg-surface border border-border rounded-card shadow-xl"
    >
      <div className="flex flex-col gap-3 p-5">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary" />
          <h2 id="rule-draft-title" className="text-base font-medium text-foreground">
            AI 规则草稿
          </h2>
          {draft?.model && <span className="text-xs text-muted">· {draft.model}</span>}
          {typeof draft?.latency_ms === 'number' && (
            <span className="text-xs text-muted">· {draft.latency_ms}ms</span>
          )}
        </div>

        {pattern && (
          <p className="text-xs text-secondary">
            基于 <b>{pattern.note_count}</b> 条
            {pattern.tag ? `#${pattern.tag}` : pattern.type}
            类型笔记提炼 → 共 {pattern.sample_total} 条候选摘要,已采样前 5 条
          </p>
        )}

        {drafting && <p className="text-sm text-muted">AI 提炼中…</p>}

        {draft && (
          <>
            {draft.rationale && (
              <p className="rounded-btn bg-elevated/40 p-2 text-xs text-secondary italic">
                {draft.rationale}
              </p>
            )}

            <label className="flex flex-col gap-1 text-xs text-secondary">
              分类
              <input
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                placeholder="如:止损 / 仓位 / 选股"
                className="rounded-btn bg-elevated border border-border px-3 py-1.5 text-sm text-foreground placeholder:text-muted focus:outline-none focus:border-primary/50"
              />
            </label>

            <label className="flex flex-col gap-1 text-xs text-secondary">
              规则标题
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="rounded-btn bg-elevated border border-border px-3 py-1.5 text-sm text-foreground focus:outline-none focus:border-primary/50"
              />
            </label>

            <label className="flex flex-col gap-1 text-xs text-secondary">
              触发条件(每行一条)
              <textarea
                value={triggers}
                onChange={(e) => setTriggers(e.target.value)}
                rows={4}
                className="rounded-btn bg-elevated border border-border px-3 py-1.5 text-sm text-foreground focus:outline-none focus:border-primary/50 resize-y"
              />
            </label>

            <label className="flex flex-col gap-1 text-xs text-secondary">
              例外情况(可选)
              <input
                value={exceptions}
                onChange={(e) => setExceptions(e.target.value)}
                className="rounded-btn bg-elevated border border-border px-3 py-1.5 text-sm text-foreground focus:outline-none focus:border-primary/50"
              />
            </label>
          </>
        )}

        {error && <p className="text-sm text-rose-300">{error}</p>}

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            disabled={adopting}
            className="px-3 py-1.5 rounded-btn text-sm text-secondary hover:text-foreground hover:bg-elevated"
          >
            丢弃
          </button>
          <button
            type="button"
            onClick={handleAdopt}
            disabled={!draft || adopting}
            className="px-3 py-1.5 rounded-btn text-sm bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {adopting ? '采纳中…' : '采纳为我的规则'}
          </button>
        </div>
      </div>
    </Modal>
  )
}