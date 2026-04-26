import React from 'react';
import styles from './Sidebar.module.css';

let instruments = [];


const Sidebar = ({ onAddInstrument }) => {
  return (
    <div className={styles.sidebar}>
      <p>No instruments added.</p>
      {/* TODO : Conditional Rendering based on instrument configuration*/}
      <div className={styles.instrumentList}>
        <p>Instruments</p>
        <br />
        <ul>
          <div className={styles.instrument}>
          {/* TODO : while in setup, change settings per instrument */}
          </div>
          <div className={styles.instrument}>

          </div>
        </ul>
      </div>
      <br />
      <div className={styles.mix}>
        <p>Mix</p>
        <br />
      </div>
      <div className={styles.addInstrument}>
        <button onClick={onAddInstrument} id={styles.addInstrumentButton}>Add Instruments</button>
      </div>
    </div>
  );
};

export default Sidebar;