import React, {useState} from 'react';
import styles from './Header.module.css';

import { invoke } from '@tauri-apps/api/core';


const Header = ({ activeTab, setActiveTab, pipelineStatus, onStart, onStop }) => {
  const isIdle     = pipelineStatus === 'idle';
  const isLaunching = pipelineStatus === 'launching';
  const isRunning  = pipelineStatus === 'running';
  const isStopping = pipelineStatus === 'stopping';

  return (
    <header className={styles.header}>
      <div className={styles.logo}>
        <h3>MusInfo</h3>
        <p>An interface for Harmonic Visuals</p>
      </div>
      <nav className={styles.nav}>
        <button onClick={() => setActiveTab('performance')}>Performance</button>
        <button onClick={() => setActiveTab('setup')}>Setup</button>
        <button onClick={() => setActiveTab('osc')}>OSC config</button>
      </nav>
      <div className={styles.controls}>

        {isLaunching && <span className={styles.statusLaunching}>Launching pipeline...</span>}
        {isRunning   && <span className={styles.statusListening}>Listening...</span>}
        {isStopping  && <span className={styles.statusStopping}>Shutting down...</span>}

        {isIdle ? (
          <>
          <button onClick={onStart} className={styles.startButton}>Start</button>
          </>
        ) : (
          <button
            onClick={onStop}
            disabled={isLaunching || isStopping}
            className={`${styles.stopButton} ${(isLaunching || isStopping) ? styles.stopDisabled : ''}`}
          >
            Stop
          </button>
        )}

      </div>
    </header>
  );
};



export default Header;