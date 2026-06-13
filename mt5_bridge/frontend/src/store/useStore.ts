import { create } from 'zustand';
import type { Position, Instance } from '../types';

interface AppState {
  mt5Status: { online: boolean; text: string };
  trackerData: Position[];
  instances: Instance[];
  setMt5Status: (status: { online: boolean; text: string }) => void;
  setTrackerData: (data: Position[]) => void;
  setInstances: (instances: Instance[]) => void;
}

export const useStore = create<AppState>((set) => ({
  mt5Status: { online: false, text: 'Checking...' },
  trackerData: [],
  instances: [],
  setMt5Status: (status) => set({ mt5Status: status }),
  setTrackerData: (data) => set({ trackerData: data }),
  setInstances: (instances) => set({ instances }),
}));

