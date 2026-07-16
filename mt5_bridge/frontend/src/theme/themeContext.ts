import { createContext, useContext } from 'react';
import type { PhosphorId } from './phosphors';

export interface ThemeCtx {
  phosphor: PhosphorId;
  setPhosphor: (id: PhosphorId) => void;
}

export const ThemeContext = createContext<ThemeCtx | null>(null);

export function usePhosphor(): ThemeCtx {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('usePhosphor must be used within ThemeProvider');
  return ctx;
}
