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

    socket.on('connect', () => {
      console.log('Connected to WebSocket');
    });

    socket.on('mt5_status', (data) => {
      try {
        const parsed = typeof data === 'string' ? JSON.parse(data) : data;
        setMt5Status(parsed);
      } catch (e) {
        console.error('Error parsing status:', e);
      }
    });

    socket.on('risk_data', (data) => {
      try {
        const parsed = typeof data === 'string' ? JSON.parse(data) : data;
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
      } catch (e) {
        console.error('Error parsing risk_data:', e);
      }
    });

    socket.on('log', (data) => {
      console.log('Log message:', data);
    });

    socket.on('disconnect', () => {
      console.log('Disconnected from WebSocket');
      setMt5Status({ online: false, text: 'Disconnected' });
    });

    return () => {
      socket.disconnect();
    };
  }, [setMt5Status, setInstances, setTrackerData]);
};

