import type { JournalFilters } from '../../types';

/* Formatting rules shared by every journal panel.
   The important one: a null metric is "not computable from this sample" and must render
   as n/a, never as 0 or a sentinel — that distinction is the whole point of the backend
   returning null. */

export const usd = (v: number) =>
  v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const signedUsd = (v: number) => (v >= 0 ? '+' : '-') + '$' + usd(Math.abs(v));

export const num = (v: number | null | undefined, digits = 2, suffix = '') =>
  v === null || v === undefined || Number.isNaN(v) ? 'n/a' : v.toFixed(digits) + suffix;

export const pct = (v: number | null | undefined, digits = 1) => num(v, digits, '%');

export const signedR = (v: number | null | undefined) =>
  v === null || v === undefined ? 'n/a' : (v >= 0 ? '+' : '') + v.toFixed(2) + 'R';

/** Compact duration: 45s / 12m / 3h 20m / 2d 4h */
export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || seconds < 0) return 'n/a';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  if (h < 24) return rm ? `${h}h ${rm}m` : `${h}h`;
  const d = Math.floor(h / 24);
  const rh = h % 24;
  return rh ? `${d}d ${rh}h` : `${d}d`;
}

/** Serialise page filters into the query string every journal endpoint understands. */
export function filterQuery(f: JournalFilters, extra: Record<string, string | number> = {}) {
  const p = new URLSearchParams();
  p.set('days', String(f.days));
  if (f.symbol) p.set('symbol', f.symbol);
  if (f.magic !== undefined) p.set('magic', String(f.magic));
  if (f.direction !== undefined) p.set('direction', String(f.direction));
  if (f.outcome) p.set('outcome', f.outcome);
  if (f.date) p.set('date', f.date);
  // Carried on every request so each panel derives percentages from the *same* opening
  // capital. Panels using different denominators would not add up.
  if (f.balance !== undefined) p.set('balance', f.balance.toFixed(2));
  for (const [k, v] of Object.entries(extra)) p.set(k, String(v));
  return p.toString();
}

/** Stable key for TanStack Query — filters plus whatever the panel adds. */
export const filterKey = (f: JournalFilters) =>
  [
    f.days, f.symbol ?? '', f.magic ?? '', f.direction ?? '', f.outcome ?? '', f.date ?? '',
    f.balance ?? '',
  ] as const;

/** "+$1,234.56 · +12.35%" — a dollar figure with its percentage twin. Falls back to the
 * dollars alone when there is no account balance to measure against. */
export function moneyPct(value: number, percent: number | null | undefined) {
  return percent === null || percent === undefined
    ? signedUsd(value)
    : `${signedUsd(value)} · ${percent >= 0 ? '+' : ''}${percent.toFixed(2)}%`;
}

export const signedPct = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined ? 'n/a' : `${v >= 0 ? '+' : ''}${v.toFixed(digits)}%`;

/** An API failure that keeps the status, so the UI can say what actually went wrong
 * instead of guessing. A 404 and a 500 mean very different things to the user. */
export class ApiError extends Error {
  // Declared as fields rather than constructor parameter properties: this project builds
  // with `erasableSyntaxOnly`, which rejects the shorthand form.
  status: number;
  url: string;

  constructor(status: number, url: string, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.url = url;
  }
}

/** fetch + JSON that fails loudly and specifically. status 0 means the request never
 * reached a server (backend down, wrong port). */
export async function getJson<T>(url: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url);
  } catch {
    throw new ApiError(0, url, 'Could not reach the backend.');
  }
  if (!res.ok) {
    let detail = '';
    try {
      const body = await res.text();
      // Flask returns JSON for handled errors and an HTML page for unhandled ones.
      detail = body.trim().startsWith('{') ? (JSON.parse(body).error ?? '') : '';
    } catch {
      /* body unreadable — the status alone is still useful */
    }
    throw new ApiError(res.status, url, detail || `Request failed (${res.status}).`);
  }
  return res.json() as Promise<T>;
}

/** Human explanation for a failed journal request, aimed at the actual likely cause. */
export function explainError(err: unknown): { headline: string; detail: string } {
  const e = err instanceof ApiError ? err : null;
  if (!e) return { headline: 'Something went wrong loading this journal.', detail: String(err) };
  if (e.status === 0)
    return {
      headline: 'The backend is not responding.',
      detail: 'Is app_server.py running on port 5000?',
    };
  if (e.status === 404)
    return {
      headline: 'This journal endpoint was not found.',
      detail:
        'Either the instance no longer exists, or app_server.py is running an older build that ' +
        'predates the journal routes — restart it and reload this page.',
    };
  if (e.status >= 500)
    return {
      headline: 'The backend errored while building this journal.',
      detail:
        'Most often this means the database has not been migrated yet. Restart app_server.py ' +
        '(init_db runs on boot) and reload. If it persists, check the server console for the traceback.',
    };
  return { headline: 'Could not load this journal.', detail: e.message };
}
