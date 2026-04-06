import React, { use } from 'react';
import { useState, useEffect } from 'react';
import { invoke } from '@tauri-apps/api/core';

const AudioDevices = () => {
    const [devices, setDevices] = useState([]);

    // Fetch audio devices when the component mounts
    useEffect(() => {
        invoke('get_audio_devices').then(setDevices);
    }, []);


    return (
    <div>
      <h2>Audio Devices on this Device</h2>
      <ul>
        {devices.map((device, index) => (
            <li key={index}>{device.name}</li>
        ))}
            
      </ul>
    </div>
  );
};

export default AudioDevices;