export interface NavEntry {
  label: string;
  href: string;
  fkey: string;
  code: string;
}

export interface NavSection {
  label: string;
  items: NavEntry[];
}

// Single source of truth for the sidebar, F-key shortcuts and the
// active-module code shown in the command bar.
export const NAV_SECTIONS: NavSection[] = [
  {
    label: 'Monitor',
    items: [
      { label: 'Dashboard', href: '/', fkey: 'F1', code: 'MON' },
      { label: 'Trade Copier', href: '/copier', fkey: 'F2', code: 'CPR' },
    ],
  },
  {
    label: 'System',
    items: [{ label: 'Settings', href: '/settings', fkey: 'F3', code: 'CFG' }],
  },
];

export const NAV_ENTRIES: NavEntry[] = NAV_SECTIONS.flatMap((s) => s.items);

export function moduleCodeFor(pathname: string): string {
  const match = NAV_ENTRIES.find((e) => e.href === pathname);
  return match ? match.code : 'MON';
}
