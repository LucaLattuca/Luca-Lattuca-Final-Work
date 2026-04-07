import React, { act } from 'react';
import styles from './Tabcontent.module.css';
import Performance from './tabs/Performance';
import Setup from './tabs/Setup';
import OSCConfig from './tabs/OSCConfig';

const Tabcontent = ({ activeTab }) => {
  return (
    <div className={styles.tabcontent}>
        {activeTab === 'performance' && <Performance />}
        {activeTab === 'setup' && <Setup />}
        {activeTab === 'osc' && <OSCConfig />}
    </div>
  );
};

export default Tabcontent;
