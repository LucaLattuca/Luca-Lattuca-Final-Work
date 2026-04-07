import React from 'react';
import styles from './Header.module.css';

// link to tabcontent
const Header = () => {
  return (
    <header className={styles.header}>
      <div className={styles.logo}>
        <h3>MusInfo</h3>
        <p>An interface for Harmonic Visuals</p>
      </div>
      <nav className={styles.nav}>
        <button type="button">Performance</button>
        <button type="button">Setup</button>
        <button type="button">OSC config</button>
      </nav>
      <button className={styles.startButton}>Start</button>
    </header>
  );
};



export default Header;
