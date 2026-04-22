import React, {useState} from 'react';
import styles from './Header.module.css';

import { invoke } from '@tauri-apps/api/core';


const Header = ({ activeTab, setActiveTab }) => {
  const [isRunning, setIsRunning] = useState(false);

  const handleStart = async () => {
    try {
      setIsRunning(true);
      // start the capture process in Rust
      const result = await invoke('start_pipeline');
      console.log('[header] start_pipeline result:', result);
    }
    catch (error) {
      console.log('[header] start_pipeline error:', error);
      setIsRunning(false);
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
      <button onClick={handleStart} disabled={isRunning} className={styles.startButton}>{isRunning ? 'Running...' : 'Start'}</button>
    </header>
  );
};



export default Header;
