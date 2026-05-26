import React, { useState } from 'react';
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
  onReconcile,
  onDeleteInstrument,
  pipelineStatus,
}) => {
  const [performanceState, setPerformanceState] = useState({
    enabled: false,
    selectedKey: 'C',
    selectedScale: 'major',
  });

  console.log('[Tabcontent] pipelineStatus:', pipelineStatus);
  return (
    <div className={styles.tabcontent}>
      {activeTab === 'performance' && (
        <Performance
          performanceState={performanceState}
          setPerformanceState={setPerformanceState}
        />
      )}
      {activeTab === 'setup' && (
        <div className={styles.setupWrapper}>
          {(pipelineStatus === 'launching' || pipelineStatus === 'running' || pipelineStatus === 'stopping') && <div className={styles.veil} />}
          <Setup
            selectedInstrument={selectedInstrument}
            switchInstrument={switchInstrument}
            instruments={instruments}
            onUpdateInstrument={onUpdateInstrument}
            onSwapDevices={onSwapDevices}
            onReconcile={onReconcile}
            onDeleteInstrument={onDeleteInstrument}
          />
        </div>
      )}
      {activeTab === 'osc' && <OSCConfig instruments={instruments} />}
    </div>
  );
};

export default Tabcontent;