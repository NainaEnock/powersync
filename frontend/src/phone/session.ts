// Which household this tab/phone is, and its code. Optional helpers for B's
// App.tsx / api.ts so the rules live in one place:
//   - `/phone?home=A` pins a tab to a home (tabs share localStorage).
//   - Otherwise the last chosen home is read from localStorage.
//   - Codes are stored per home in localStorage, never in the URL.
//     (An installed iPhone app has its own storage, so enter the code there.)

import { HOME_IDS, type HomeId } from './phoneTypes';

const HOME_KEY = 'powersync.phone.home';
const tokenKey = (home: HomeId) => `powersync.phone.token.${home}`;

function asHome(v: string | null | undefined): HomeId | null {
  const up = (v ?? '').trim().toUpperCase();
  return (HOME_IDS as string[]).includes(up) ? (up as HomeId) : null;
}

function safeStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/** Home pinned by `?home=` in the URL, if any. */
export function pinnedHome(): HomeId | null {
  if (typeof window === 'undefined') return null;
  return asHome(new URLSearchParams(window.location.search).get('home'));
}

/** `?home=` wins, then the stored choice, else null (show the picker). */
export function resolveHomeId(): HomeId | null {
  return pinnedHome() ?? asHome(safeStorage()?.getItem(HOME_KEY));
}

/** Save the choice. If the tab was pinned with ?home=, keep the URL in step. */
export function storeHome(home: HomeId | null): void {
  const s = safeStorage();
  if (home) s?.setItem(HOME_KEY, home);
  else s?.removeItem(HOME_KEY);
  if (typeof window !== 'undefined') {
    const url = new URL(window.location.href);
    if (url.searchParams.has('home')) {
      if (home) url.searchParams.set('home', home);
      else url.searchParams.delete('home');
      window.history.replaceState(null, '', url.toString());
    }
  }
}

export function getHomeToken(home: HomeId): string {
  return safeStorage()?.getItem(tokenKey(home)) ?? '';
}

export function storeHomeToken(home: HomeId, token: string): void {
  const s = safeStorage();
  const t = token.trim();
  if (t) s?.setItem(tokenKey(home), t);
  else s?.removeItem(tokenKey(home));
}
