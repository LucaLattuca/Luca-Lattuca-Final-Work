import React, {useState} from 'react';
import styles from './Header.module.css';

import { invoke } from '@tauri-apps/api/core';


const Header = ({ activeTab, setActiveTab }) => {
  const [isRunning, setIsRunning] = useState(false);

  const handleStart = async () => {
    try {
      setIsRunning(true);
      const result = await invoke('start_pipeline');
      console.log('[header] start_pipeline result:', result);
    }
    catch (error) {
      console.log('[header] start_pipeline error:', error);
      setIsRunning(false);
    }
  }

  const handleStop = async () => {
    try {
      const result = await invoke('stop_pipeline');
      console.log('[header] stop_pipeline result:', result);
      setIsRunning(false);
    }
    catch (error) {
      console.log('[header] stop_pipeline error:', error);
    }
  }

  return (
    <header className={styles.header}>
      <div className={styles.logo}>
        <h3>MusInfo</h3>
        <p>An interface for Harmonic Visuals</p>
      </div>
      <nav className={styles.nav}>
        <button onClick={() => setActiveTab('performance')} >Performance</button>
        <button onClick={() => setActiveTab('setup')} >Setup</button>
        <button onClick={() => setActiveTab('osc')} >OSC config</button>
      </nav>
      <div className={styles.controls}>
        <button onClick={handleStart} disabled={isRunning} className={styles.startButton}>
          {isRunning ? 'Running...' : 'Start'}
        </button>
        <button onClick={handleStop} disabled={!isRunning} className={styles.stopButton}>
          Stop
        </button>
      </div>
    </header>
  );
};



export default Header;