const ACRONYMS: Record<string, string> = { iou: 'IoU', em: 'EM', rasa: 'RASA', staple: 'STAPLE' }

/** A readable name for a catalog identifier, such as a pipeline, strategy, option, or requirement. */
export function resolverLabel(identifier: string) {
  const text = identifier.split('_').filter(Boolean).map((word) => ACRONYMS[word] ?? word).join(' ')
  return text ? text[0]!.toLocaleUpperCase() + text.slice(1) : identifier
}
