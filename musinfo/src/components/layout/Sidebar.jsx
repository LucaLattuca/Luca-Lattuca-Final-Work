import React from 'react';
import styles from './Sidebar.module.css';


const Sidebar = ({ onAddInstrument, onSelectInstrument, selectedInstrument, instruments}) => {
  return (
    <div className={styles.sidebar}>
      <div className={styles.instrumentList}>
        <p className={styles.sidebarTitle}>Instruments</p>
      
        {Object.entries(instruments).map(([name, data]) => (
          <div
            key={name}
            className={`${styles.instrumentcard} ${selectedInstrument?.name === name ? styles.selectedInstrument : ''}`}
            onClick={() => onSelectInstrument(name, data)}
          >
            <h3>{name}</h3>
            <p>{data.audio_device.name} — Ch.{data.audio_device.channel + 1}</p>
          </div>
        ))}
        
        <p className={styles.sidebarTitle}>Mix</p>
        <div className={styles.mix}>
          {/* ADD Instrument role */}
        </div>
      </div>

      
      <div className={styles.addInstrument}>
        <button onClick={onAddInstrument} className={styles.addInstrumentButton}>
          Add Instruments
        </button>
      </div>
    </div>
  );
};

export default Sidebar;