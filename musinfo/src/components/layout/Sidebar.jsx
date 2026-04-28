import React from 'react';
import styles from './Sidebar.module.css';
import instruments from '../../../backend/config/instruments.json';
let instrument_list = instruments;


const Sidebar = ({ onAddInstrument }) => {
  return (
    <div className={styles.sidebar}>
      {/* <p>No instruments added.</p> */}
      <div className={styles.instrumentList}>
        <p className={styles.sidebarTitle}>Instruments</p>
      
          {Object.entries(instrument_list.instruments).map(([name, instrument]) => (
              <div className={styles.instrumentcard} key={name}>
                
                <h3>{name}</h3>
                <p>{instrument.audio_device.name} - Ch.{instrument.audio_device.channel + 1}</p>
                
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