import React, { act } from 'react';
import styles from './Tabcontent.module.css';
import Performance from '../tabs/Performance/Performance';
import Setup from '../tabs/Setup/Setup';
import OSCConfig from '../tabs/OSCConfig/OSCConfig';


const Tabcontent = ({
  activeTab,
  selectedInstrument,
  switchInstrument,
  instruments,
  onUpdateInstrument,
  onSwapDevices,
}) => {
  return (
    <div className={styles.tabcontent}>
      {activeTab === 'performance' && <Performance />}
      {activeTab === 'setup' && (
        <Setup
          selectedInstrument={selectedInstrument}
          switchInstrument={switchInstrument}
          instruments={instruments}
          onUpdateInstrument={onUpdateInstrument}
          onSwapDevices={onSwapDevices}
        />
      )}
      {activeTab === 'osc' && <OSCConfig />}
    </div>
  );
};

export default Tabcontent;
