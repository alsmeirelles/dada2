export function resolverLabel(identifier: string) {
  const words = identifier.replaceAll('_', ' ').trim()
  return words ? words[0]!.toLocaleUpperCase() + words.slice(1) : identifier
}
