import React from 'react';
import styles from './Tabcontent.module.css';
import AudioDevices from '../audio-devices/AudioDevices';
// TODO load content components based on selected tab
const Tabcontent = () => {
  return (
    <div className={styles.tabcontent}>
        <AudioDevices />
    </div>
  );
};

export default Tabcontent;