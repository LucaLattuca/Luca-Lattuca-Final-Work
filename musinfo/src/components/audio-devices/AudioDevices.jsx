import React, { use } from 'react';
import { useState, useEffect } from 'react';
import { invoke } from '@tauri-apps/api/core';
import styles from './AudioDevices.module.css';
import refreshIcon from '../../assets/refresh.svg';


const AudioDevices = () => {
    const [devices, setDevices] = useState([]);
    const [reload, setReload] = useState(false);

    // Fetch audio devices when the component mounts
    useEffect(() => {
        invoke('get_audio_devices').then(setDevices);
    }, [reload]);


    return (
    <div className={styles.audioDevices}>
      <h2>Audio Devices on this Device</h2>
      <button onClick={() => setReload(!reload)} className={styles.refreshButton}>
        <img src={refreshIcon} alt="Reload" className={styles.refreshIcon}/>
      </button>
      <ul>
        {devices.map((device, index) => (
            <li key={index}>{device.name}</li>
        ))}
            
      </ul>
    </div>
  );
};

export default AudioDevices;