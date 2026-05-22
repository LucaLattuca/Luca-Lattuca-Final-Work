import React from 'react';
import styles from './Sidebar.module.css';


const Sidebar = ({ onAddInstrument, onSelectInstrument, selectedInstrument, instruments}) => {
  
  
  const mixInstruments = {};
  const regularInstruments = {};
  
  Object.entries(instruments).forEach(([name, data]) => {
    if (data.type === 'mix') {
      mixInstruments[name] = data;
    } else {
      regularInstruments[name] = data;
    }
  });

  return (
    <div className={styles.sidebar}>
      <div className={styles.instrumentList}>
        <p className={styles.sidebarTitle}>Instruments</p>
        

        {Object.entries(regularInstruments).map(([name, data]) => {
            const isMidi = data.type === 'midi';
            const disconnected = isMidi
                ? data.midi_device?.connected === false
                : data.audio_device?.connected === false;
        
            return (
                <div
                    key={name}
                    className={`${styles.instrumentcard} ${selectedInstrument?.name === name ? styles.selectedInstrument : ''} ${disconnected ? styles.disconnectedInstrument : ''}`}
                    onClick={() => onSelectInstrument(name, data)}
                >
                    <h3>{name}</h3>
                    {disconnected
                        ? <p className={styles.deviceNotFound}>device not found</p>
                        : isMidi
                            ? <p>{data.midi_device?.name ?? 'No MIDI device'}</p>
                            : <p>{data.audio_device?.name} — Ch.{(data.audio_device?.channel ?? 0) + 1}</p>
                    }
                </div>
            );
        })}
        
        {Object.entries(regularInstruments).length > 1 &&(
          <>
            <p className={styles.sidebarTitle}>Mix</p>
            <div className={styles.mixSection}>
              {Object.entries(mixInstruments).map(([name, data]) => {
                // Check if internal mix or external mix
                const isInternalMix = data.mix_source === 'internal';

                // Show different info based on source
                const sourceDisplay = isInternalMix
                ? 'internal mix' 
                : `${data.audio_device?.name || 'Unknown'} — Ch.${(data.audio_device?.channel || 0) + 1}`;

                return (
                  <div
                  key={name}
                  className={`${styles.instrumentcard} ${styles.mixCard} ${selectedInstrument?.name === name ? styles.selectedInstrument : ''}`}
                  onClick={() => onSelectInstrument(name, data)}
                  >
                    <h3>{name}</h3>
                    <p>{sourceDisplay}</p>
                  </div>
                );
              })}
            </div>
          </>
        )}

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