import { AlertTriangle } from 'lucide-react'
import { useEffect, useId, useRef, useState, type ReactNode } from 'react'

import { Button } from '../../components/ui/Button'
import { errorText } from './consensus-view-model'

type ConfirmDialogProps = {
  title: string
  effect: string
  confirmLabel: string
  rationale: 'required' | 'optional' | 'none'
  rationaleLabel?: string
  notes?: string[]
  pending?: boolean
  error?: unknown
  /** Further inputs the action needs, shown above the rationale. */
  children?: ReactNode
  confirmDisabled?: boolean
  onConfirm: (rationale: string) => void
  onCancel: () => void
}

/** A confirmation that states an action's effect and collects its rationale before sending it. */
export function ConfirmDialog({ title, effect, confirmLabel, rationale, rationaleLabel, notes = [], pending, error, children, confirmDisabled, onConfirm, onCancel }: ConfirmDialogProps) {
  const titleId = useId()
  const fieldId = useId()
  const [text, setText] = useState('')
  const dialogRef = useRef<HTMLDivElement>(null)
  const missing = rationale === 'required' && !text.trim()

  useEffect(() => dialogRef.current?.querySelector<HTMLElement>('textarea, button')?.focus(), [])

  useEffect(() => {
    function escape(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', escape)
    return () => window.removeEventListener('keydown', escape)
  }, [onCancel])

  return <div className="confirm-backdrop">
    <div ref={dialogRef} className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId}>
      <h2 id={titleId}>{title}</h2>
      <p>{effect}</p>
      {notes.map((note) => <p key={note} className="muted">{note}</p>)}
      {children}
      {rationale !== 'none' && <label htmlFor={fieldId} className="confirm-rationale">
        {rationaleLabel ?? (rationale === 'required' ? 'Rationale (required)' : 'Note (optional)')}
        <textarea id={fieldId} value={text} maxLength={2000} onChange={(event) => setText(event.target.value)} />
      </label>}
      {error !== undefined && error !== null && <ErrorNotice error={error} />}
      <div className="confirm-actions">
        <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button type="button" disabled={missing || pending || confirmDisabled} onClick={() => onConfirm(text.trim())}>{confirmLabel}</Button>
      </div>
    </div>
  </div>
}

/** An API failure with its trace ID. */
export function ErrorNotice({ error }: { error: unknown }) {
  return <p className="form-error" role="alert"><AlertTriangle size={15} /> {errorText(error)}</p>
}
