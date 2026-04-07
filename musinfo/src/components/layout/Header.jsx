import React from 'react';
import styles from './Header.module.css';


const Header = ({ activeTab, setActiveTab }) => {
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
      <button className={styles.startButton}>Start</button>
    </header>
  );
};



export default Header;
