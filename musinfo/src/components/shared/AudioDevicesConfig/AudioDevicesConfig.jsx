import React, { useState, useEffect } from 'react';
import { invoke } from '@tauri-apps/api/core';
import styles from './AudioDevicesConfig.module.css';



const AudioDevicesConfig = ({ inputType, selectedDevice, onSelectDevice }) => {
  const [devices, setDevices]   = useState([]);
  const [loading, setLoading]   = useState(false);
  const [error,   setError]     = useState(null);

  useEffect(() => {
    fetchDevices();
  }, [inputType]);

  const fetchDevices = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = inputType === 'midi'
        ? await invoke('get_midi_devices')
        : await invoke('get_audio_devices', { deviceType: inputType });
    
      setDevices(result);
    
      // auto-select: find matching device by name + channel
      // device_id can change between sessions so we match by name
      if (selectedDevice?.name) {
        const match = result.find(d =>
          d.name === selectedDevice.name &&
          (d.channel ?? 0) === (selectedDevice.channel ?? 0)
        );
        if (match) {
          onSelectDevice({
            name:               match.name,
            device_id:          match.device_index ?? match.index,
            host_api:           match.host_api,
            max_input_channels: match.max_input_channels,
            channel:            match.channel ?? 0,
            sample_rate:        match.sample_rate,
          });
        }
      }
    
    } catch (err) {
      setError('Could not load devices. Is the interface connected?');
      console.error('[AudioDevicesConfig]', err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={styles.AudioDevicesConfig}>
      <div className={styles.deviceListHeader}>
        <p className={styles.stepHint}>Available devices</p>
        <button className={styles.reloadBtn} onClick={fetchDevices} disabled={loading}>
          {loading ? '...' : '↻ Reload'}
        </button>
      </div>

    {/* TODO: make device show up even if not connected + custom border styling for activated device or not  */}

      {error && <p>{error}</p>}

      {!loading && !error && devices.length === 0 && (
        <p className={styles.hintText}>No devices found. Is the device connected?</p>
      )}

         <div className={styles.deviceList}>
        {loading && <p className={styles.hintText}>Scanning devices...</p>}

        {!loading && devices.map((device, i) => {
          const isSelected =
            selectedDevice?.device_id === (device.device_index ?? device.index) &&
            selectedDevice?.channel   === (device.channel ?? 0);

          return (
            <div key={i} className={styles.deviceCard}>
              <button
                className={`${styles.deviceBtn} ${isSelected ? styles.selectedDevice : ''}`}
                onClick={() => onSelectDevice({
                  name:               device.name,
                  device_id:          device.device_index ?? device.index,
                  host_api:           device.host_api,
                  max_input_channels: device.max_input_channels,
                  channel:            device.channel ?? 0,
                  sample_rate:        device.sample_rate,
                })}
              >
                <div className={styles.deviceInfo}>
                  <h4 className={styles.deviceName}>{device.name}</h4>
                  <div className={styles.deviceDetails}>
                    <p>{device.host_api}</p>
                    <p>Ch.{device.channel}</p>
                    <p>{device.sample_rate}Hz</p>
                    <p>{device.latency}ms</p>
                  </div>
                </div>
                <div className={styles.deviceStatus}>
                  <p>in use</p>
                </div>
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default AudioDevicesConfig;