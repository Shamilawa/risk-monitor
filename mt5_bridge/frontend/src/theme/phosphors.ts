export type PhosphorId = 'amber' | 'green' | 'blue' | 'cyan' | 'red' | 'mono';

export interface Phosphor {
  id: PhosphorId;
  label: string;
  /** swatch color shown in the picker (matches the CSS accent for this phosphor) */
  swatch: string;
}

// Order shown in the picker. Swatches mirror --terminal-accent in terminal.css.
export const PHOSPHORS: Phosphor[] = [
  { id: 'amber', label: 'AMBER', swatch: '#ffb000' },
  { id: 'green', label: 'GREEN', swatch: '#22e57a' },
  { id: 'blue', label: 'BLUE', swatch: '#4d9fff' },
  { id: 'cyan', label: 'CYAN', swatch: '#2fe0e0' },
  { id: 'red', label: 'RED', swatch: '#ff5c57' },
  { id: 'mono', label: 'MONO', swatch: '#d6d9e0' },
];

export const DEFAULT_PHOSPHOR: PhosphorId = 'amber';
const STORAGE_KEY = 'rm-phosphor';

export function isPhosphorId(v: unknown): v is PhosphorId {
  return typeof v === 'string' && PHOSPHORS.some((p) => p.id === v);
}

export function loadPhosphor(): PhosphorId {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (isPhosphorId(v)) return v;
  } catch {
    /* localStorage unavailable — fall through to default */
  }
  return DEFAULT_PHOSPHOR;
}

/** Persist + apply the phosphor by stamping data-phosphor on <html>. */
export function applyPhosphor(id: PhosphorId): void {
  document.documentElement.setAttribute('data-phosphor', id);
  try {
    localStorage.setItem(STORAGE_KEY, id);
  } catch {
    /* ignore persistence failure */
  }
}
