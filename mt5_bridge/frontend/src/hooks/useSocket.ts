import { useEffect } from 'react';
import { io } from 'socket.io-client';
import { useStore } from '../store/useStore';
import type { Instance, Position } from '../types';

export const useSocket = () => {
  const setMt5Status = useStore((state) => state.setMt5Status);
  const setInstances = useStore((state) => state.setInstances);
  const setTrackerData = useStore((state) => state.setTrackerData);

  useEffect(() => {
    // Connect to the same host that served the page
    const socket = io();

    // Socket events can back up into many queued browser tasks when the tab
    // sits backgrounded/throttled for a long time (e.g. switching to another
    // Windows virtual desktop, which doesn't always disconnect the socket
    // below). Draining that backlog by calling setState once per message
    // fires one React re-render per queued message and freezes the UI when
    // the tab regains focus. Instead, only keep the latest pending payload
    // and flush it into the store at most once per animation frame.
    let pendingStatus: { online: boolean; text: string } | null = null;
    let pendingInstances: Instance[] | null = null;
    let rafId: number | null = null;

    const flush = () => {
      rafId = null;
      if (pendingStatus) {
        setMt5Status(pendingStatus);
        pendingStatus = null;
      }
      if (pendingInstances) {
        const parsed = pendingInstances;
        pendingInstances = null;
        setInstances(parsed);

        // Flatten positions across all instances for the active positions table
        const allPositions = parsed.flatMap((inst: Instance) =>
          (inst.positions || []).map((p: Position) => ({
            ...p,
            instanceName: inst.name,
            instanceId: inst.id,
            open_price: p.price_open,
            current_price: p.price_current,
          }))
        );
        setTrackerData(allPositions);
      }
    };

    const scheduleFlush = () => {
      if (rafId === null) {
        rafId = requestAnimationFrame(flush);
      }
    };

    socket.on('connect', () => {
      console.log('Connected to WebSocket');
    });

    socket.on('mt5_status', (data) => {
      try {
        pendingStatus = typeof data === 'string' ? JSON.parse(data) : data;
        scheduleFlush();
      } catch (e) {
        console.error('Error parsing status:', e);
      }
    });

    socket.on('risk_data', (data) => {
      try {
        const parsed = typeof data === 'string' ? JSON.parse(data) : data;
        if (Array.isArray(parsed)) {
          parsed.sort((a: Instance, b: Instance) => a.id - b.id);
        }
        pendingInstances = parsed;
        scheduleFlush();
      } catch (e) {
        console.error('Error parsing risk_data:', e);
      }
    });

    socket.on('log', (data) => {
      console.log('Log message:', data);
    });

    socket.on('disconnect', () => {
      console.log('Disconnected from WebSocket');
      pendingStatus = { online: false, text: 'Disconnected' };
      scheduleFlush();
    });

    // Disconnect when the tab is hidden so it doesn't keep streaming (and
    // queuing) risk_data while backgrounded, and reconnect on return.
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'hidden') {
        socket.disconnect();
      } else {
        socket.connect();
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      if (rafId !== null) cancelAnimationFrame(rafId);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      socket.disconnect();
    };
  }, [setMt5Status, setInstances, setTrackerData]);
};

