import React, { useState, useEffect, useRef } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import styles from './TestMidi.module.css';

const TestMidi = ({ deviceName }) => {
  const [listening, setListening]   = useState(false);
  const [lastEvent, setLastEvent]   = useState(null);
  const unlistenRef = useRef(null);

  // clean up on unmount
    useEffect(() => {
      return () => {
        invoke('stop_midi_test').catch(() => {});
        if (unlistenRef.current) unlistenRef.current();
      };
    }, []);

  const start = async () => {
    if (!deviceName) return;
    console.log('[TestMidi] Starting for device:', deviceName);
    try {
      const result = await invoke('test_midi_input', { deviceName });
      console.log('[TestMidi] invoke result:', result);
      unlistenRef.current = await listen('midi-event', (e) => {
        console.log('[TestMidi] event received:', e.payload);
        setLastEvent(e.payload);
      });
      setListening(true);
    } catch (err) {
      console.error('[TestMidi] invoke failed:', err);
    }
  };

  const stop = async () => {
    await invoke('stop_midi_test');
    if (unlistenRef.current) { unlistenRef.current(); unlistenRef.current = null; }
    setListening(false);
    setLastEvent(null);
  };

  return (
    <div className={styles.testMidi}>
      <div className={styles.header}>
        <button
          className={`${styles.toggleBtn} ${listening ? styles.active : ''}`}
          onClick={listening ? stop : start}
          disabled={!deviceName}
        >
          {listening ? 'Stop' : 'Test'}
        </button>
        <p className={styles.status}>
          {listening
            ? `Listening to ${deviceName}...`
            : deviceName ? 'Press Test to monitor MIDI input' : 'No MIDI device selected'}
        </p>
      </div>

      <div className={styles.eventDisplay}>
        {lastEvent?.error ? (
          <p className={styles.error}>{lastEvent.error}</p>
        ) : lastEvent ? (
          <>
            <p><span>Type</span>{lastEvent.type === 'note_on' ? 'Note On' : 'Note Off'}</p>
            <p><span>Note</span>{lastEvent.note}</p>
            <p><span>Velocity</span>{lastEvent.velocity}</p>
          </>
        ) : (
          <p className={styles.hint}>No events yet</p>
        )}
      </div>
    </div>
  );
};

export default TestMidi;