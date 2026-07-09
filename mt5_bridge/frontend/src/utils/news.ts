import type { NewsWindow } from '../types';

export type WindowState = 'upcoming' | 'active' | 'passed';

export const computeWindowState = (w: NewsWindow, nowSec: number = Date.now() / 1000): WindowState => {
  if (nowSec < w.start) return 'upcoming';
  if (nowSec <= w.end) return 'active';
  return 'passed';
};

export const findActiveWindow = (events: NewsWindow[], nowSec: number = Date.now() / 1000): NewsWindow | undefined => {
  return events.find((w) => nowSec >= w.start && nowSec <= w.end);
};
