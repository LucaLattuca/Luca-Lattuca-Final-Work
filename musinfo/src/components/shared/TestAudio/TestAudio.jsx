import React, { useState, useEffect } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import styles from './TestAudio.module.css';

const TestAudio = ({ deviceId, channel }) => {
  const [isTesting,  setIsTesting]  = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [peak,       setPeak]       = useState(0);

  // unlisten + stop stream on unmount or when device changes
  useEffect(() => {
    let unlisten;

    const startListening = async () => {
      unlisten = await listen('test-audio-level', (event) => {
        const level = event.payload;
        setAudioLevel(level);
        setPeak(prev => Math.max(prev, level));
      });
    };

    startListening();

    return () => {
      invoke('stop_device_test').catch(console.error);
      setIsTesting(false);
      setAudioLevel(0);
      setPeak(0);
      if (unlisten) unlisten();
    };
  }, []);

  // stop and reset when the device selection changes mid-test
  useEffect(() => {
    if (!isTesting) return;
    invoke('stop_device_test').catch(console.error);
    setIsTesting(false);
    setAudioLevel(0);
    setPeak(0);
  }, [deviceId, channel]);

  const handleTestToggle = async () => {
    if (isTesting) {
      await invoke('stop_device_test');
      setIsTesting(false);
    } else {
      await invoke('test_device_audio', { deviceId, channel });
      setIsTesting(true);
      setPeak(0);
    }
  };

  return (
    <div className={styles.testDevice}>
      <div className={styles.testControls}>
        <p className={styles.testDeviceTitle}>Live signal</p>
        <button
          className={`${styles.testBtn} ${isTesting ? styles.testBtnActive : ''}`}
          onClick={handleTestToggle}
          disabled={deviceId == null}
        >
          {isTesting ? 'Stop test' : 'Start test'}
        </button>
      </div>

      <div className={styles.testResult}>
        <div
          className={`${styles.levelBar} ${audioLevel > 0.01 ? styles.levelBarActive : ''}`}
          style={{ width: `${audioLevel * 100}%` }}
        />
      </div>

      <p className={styles.testMetrics}>
        RMS: {audioLevel.toFixed(3)} &nbsp;|&nbsp; Peak: {peak.toFixed(3)}
      </p>
    </div>
  );
};

export default TestAudio;