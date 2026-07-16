import { useEffect, useState, type ReactNode } from 'react';
import { applyPhosphor, loadPhosphor, type PhosphorId } from './phosphors';
import { ThemeContext } from './themeContext';

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [phosphor, setPhosphorState] = useState<PhosphorId>(() => loadPhosphor());

  // Stamp the attribute on first mount and whenever it changes.
  useEffect(() => {
    applyPhosphor(phosphor);
  }, [phosphor]);

  const setPhosphor = (id: PhosphorId) => setPhosphorState(id);

  return <ThemeContext.Provider value={{ phosphor, setPhosphor }}>{children}</ThemeContext.Provider>;
}
