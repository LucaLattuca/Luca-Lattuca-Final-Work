import React, { useState, useEffect } from 'react';
import { invoke } from '@tauri-apps/api/core';
import styles from './AudioDevicesConfig.module.css';


const AudioDevicesConfig = ({ 
  inputType,
  selectedDevice,
  onSelectDevice,
  onSwapDevice,
  currentInstrumentName,
  allInstruments, 
  onReconcile,
 }) => {

  const [devices,     setDevices]     = useState([]);
  const [loading,     setLoading]     = useState(false);
  const [error,       setError]       = useState(null);

  const [usedDevices, setUsedDevices] = useState([]);
  const [swapPrompt,  setSwapPrompt]  = useState(null);

  // Re-fetch the device list whenever the input type changes (audio / midi / virtual).
  useEffect(() => { fetchDevices(); }, [inputType]); 


  // Recompute what decives are in use, runs when instruments gets updated
  useEffect(() => {
    const instruments = allInstruments ?? {};
    const used = Object.entries(instruments)
      .filter(([name]) => name !== currentInstrumentName)
      .map(([name, inst]) => ({
        instrumentName: name,
        name:           inst.audio_device?.name,
        channel:        inst.audio_device?.channel,
      }));
    setUsedDevices(used);
  }, [allInstruments, currentInstrumentName]);


  const fetchDevices = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = inputType === 'midi'
        ? await invoke('get_midi_devices')
        : await invoke('get_audio_devices', { deviceType: inputType });
      setDevices(result);

      if (onReconcile) {
        const updated = await invoke('reconcile_devices');
        onReconcile(updated.instruments);
      }

    } catch (err) {
      setError('Could not load devices. Is the interface connected?');
      console.error('[AudioDevicesConfig]', err);
    } finally {
      setLoading(false);
    }
  };


  const handleDeviceClick = (device) => {
    const usedEntry = usedDevices.find(u =>
      u.name    === device.name &&
      u.channel === (device.channel ?? 0)
    );

    if (usedEntry) {
      // Setup context: open swap prompt.
      // Modal context (no onSwapDevice): click is blocked via disabled attr.
      if (onSwapDevice) setSwapPrompt({ otherName: usedEntry.instrumentName, device });
      return;
    }

    onSelectDevice({
      name:               device.name,
      device_id:          device.device_index ?? device.index,
      host_api:           device.host_api,
      max_input_channels: device.max_input_channels,
      channel:            device.channel ?? 0,
      sample_rate:        device.sample_rate,
    });
  };

  // confirmation propmpt for swapping audio devices
  const confirmSwap = () => {
    if (!swapPrompt) return;
    onSwapDevice(swapPrompt.otherName, {
      name:               swapPrompt.device.name,
      device_id:          swapPrompt.device.device_index ?? swapPrompt.device.index,
      host_api:           swapPrompt.device.host_api,
      max_input_channels: swapPrompt.device.max_input_channels,
      channel:            swapPrompt.device.channel ?? 0,
      sample_rate:        swapPrompt.device.sample_rate,
    });
    setSwapPrompt(null);
  };

  return (
    <div className={styles.AudioDevicesConfig}>

      {/* swap confirmation — only reachable from Setup, not the modal */}
      {swapPrompt && (
        <div className={styles.swapOverlay}>
          <div className={styles.swapModal}>
            <p className={styles.swapTitle}>
              Swap with <strong>{swapPrompt.otherName}</strong>?
            </p>
            <p className={styles.swapDetail}>
              {swapPrompt.device.name} — Ch.{(swapPrompt.device.channel ?? 0) + 1}
            </p>
            <div className={styles.swapActions}>
              <button className={styles.swapCancel} onClick={() => setSwapPrompt(null)}>
                Cancel
              </button>
              <button className={styles.swapConfirm} onClick={confirmSwap}>
                Swap
              </button>
            </div>
          </div>
        </div>
      )}

      {/* header */}
      <div className={styles.deviceListHeader}>
        <p className={styles.stepHint}>Available devices</p>
        <button className={styles.reloadBtn} onClick={fetchDevices} disabled={loading}>
          {loading ? '...' : '↻ Reload'}
        </button>
      </div>

      {error && <p>{error}</p>}

      {!loading && !error && devices.length === 0 && (
        <p className={styles.hintText}>No devices found. Is the device connected?</p>
      )}

      {/* device list */}
      <div className={styles.deviceList}>
        {loading && <p className={styles.hintText}>Scanning devices...</p>}

        {!loading && devices.map((device, i) => {
          // Compare by name + channel rather than device_id — the id is a hardware
          // index that can change between sessions, name + channel is stable.
          const isSelected =
            selectedDevice?.name    === device.name &&
            selectedDevice?.channel === (device.channel ?? 0) &&
            selectedDevice?.host_api === device.host_api;

          const usedEntry = usedDevices.find(u =>
            u.name    === device.name &&
            u.channel === (device.channel ?? 0)
          );
          const isInUse = !!usedEntry;

          return (
            <div key={i} className={styles.deviceCard}>
              <button
                className={`
                  ${styles.deviceBtn}
                  ${isSelected ? styles.selectedDevice : ''}
                  ${isInUse   ? styles.inUseDevice    : ''}
                `}
                onClick={() => handleDeviceClick(device)}
                // in modal context: block in-use devices entirely
                // in Setup context: allow click to trigger swap prompt
                disabled={isInUse && !onSwapDevice}
              >
                <div className={styles.deviceInfo}>
                  <h4 className={styles.deviceName}>{device.name}</h4>
                  <div className={styles.deviceDetails}>
                    <p>{device.host_api}</p>
                    <p>Ch.{(device.channel ?? 0) + 1}</p>
                    <p>{device.sample_rate}Hz</p>
                    <p>{device.latency}ms</p>
                  </div>
                </div>
                <div className={styles.deviceStatus}>
                  {isInUse && <p>in use by {usedEntry.instrumentName}</p>}
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