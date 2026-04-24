import React, { useState, useEffect, useCallback } from 'react';
import styles from './AddInstrumentModal.module.css';
import { invoke } from '@tauri-apps/api/core';
import modelsConfig  from '../../../backend/config/models.json';


const STEP_LABELS = ['Choose input type', 'Select device', 'Configure', 'Test signal'];

const INPUT_TYPES = [
  {
    id: "midi",
    label: "MIDI",
    description: "Keyboard, pad controllers, or any MIDI devices",
    icon: "♪",
  },
  {
    id: "audio",
    label: "Audio",
    description: "Microphone, guitar, line-in via audio interface...",
    icon: "♫",
  },
  {
    id: "virtual",
    label: "Virtual",
    description: "Software instruments or DAW outputs",
    icon: "🌐",
  },
]


const AVAILABLE_MODELS = Object.entries(modelsConfig.models).map(([id, data]) => ({
  id,
  ...data,
}));


const AddInstrumentModal = ({ onClose, onSubmit }) => {
  const [step, setStep] = useState(0);
  // instrument object to update instruments.json with
  const [formData, setFormData] = useState({
    name: '',
    audio_device: '',
    channel: 0,
    models: [],
  });
  
  // audio device state
  const [devices, setDevices]     = useState([]);
  const [loadingDevices, setLoadingDevices] = useState(false);
  const [deviceError, setDeviceError]       = useState(null);

  // hover state for model cards to show description
  const [hoveredModel, setHoveredModel] = useState(null);
  
  // fetch audio devices when in step 2
  useEffect(() => { if (step === 1) fetchDevices(); }, [step]);


  // invoke Rust command to fetch devices based on input type
  const fetchDevices = async () => {
    setLoadingDevices(true);
    setDeviceError(null);
    try {
      if (formData.type === 'midi') {
        const result = await invoke('get_midi_devices');
        setDevices(result);
      } else {
        const result = await invoke('get_audio_devices', { deviceType: formData.type });
        setDevices(result);
      }
    } catch (err) {
      setDeviceError('Could not load devices. Is the interface connected?');
      console.error('[Step2]', err);
    } finally {
      setLoadingDevices(false);
    }
  };



  // update fields
  const patch = (fields) => setFormData(prev => ({ ...prev, ...fields }));
  // prevent going to next step if required fields are not filled
  const canContinue = 
    step === 0 ? !!formData.type :
    step === 1 ? !!formData.selectedDevice :
    step === 2 ? formData.models.length > 0 && !!formData.name :
    true;

  return (
    <div className={styles.overlay}>
      <div className={styles.modal}>


        {/* Header */}
        <div className={styles.modalHeader}>
          <h2>Add instrument : {STEP_LABELS[step]}</h2>
          <button className={styles.closeButton} onClick={onClose}>x</button>
        </div>


        {/* Steps indicator */}
        <div className={styles.stepIndicator}>
          {STEP_LABELS.map((label, i) => (
            <div key={label} className={styles.stepItem}>
              <div className={`${styles.stepDot} ${i < step ? styles.done : ''} ${i === step ? styles.active : ''}`}>
                {i < step ? '✔' : i + 1}
              </div>
              {i < STEP_LABELS.length - 1 && (
                <div className={`${styles.stepLine} ${i < step ? styles.done : ''}`} />
              )}
            </div>
          ))}
        </div>

        
          
        {/* load step one : Input type */}
        {step === 0 &&(
          <div className={styles.stepContent}>
            
            <div className={styles.InputCards}>
              {INPUT_TYPES.map(({id, label, description, icon}) => (
                <button
                key={id}
                className={`${styles.card} ${formData.type === id ? styles.selectedCard : ''}`}
                onClick={() => patch({ type: id })}
                >
                <p className={styles.cardIcon}>{icon}</p>
                <h2 className={styles.cardLabel}>{label}</h2>
                <p className={styles.cardDesc}>{description}</p>

                </button>
              ))}
            </div>
          </div>
        )}
        
  
       

        {/* Step 2 */}
        {step === 1 &&(
          <div className={styles.stepContent}>

            <div className={styles.deviceListHeader}>
                <p className={styles.stepHint}>Available devices</p>

                <button className={styles.reloadBtn} onClick={fetchDevices} disabled={loadingDevices}>
                  {loadingDevices ? '...' : '↻ Reload'}
                </button>

            </div>

             {deviceError && (
                <p>{deviceError}</p>
              )}
              
              {!loadingDevices && !deviceError && devices.length === 0 && (
                <p className={styles.hintText}>No devices found. Is the device connected?</p>
              )}


            <div className={styles.deviceList}>
            
              {loadingDevices && <p className={styles.hintText}>Scanning devices...</p>}

              {!loadingDevices && devices.map((device, i) => {
                const deviceKey = `${device.device_index ?? device.index}-ch${device.channel ?? 0}`;
                const isSelected = formData.selectedDevice === deviceKey;
                return (
                  <div key={i} className={styles.deviceCard}>
                  <button className={`${styles.deviceBtn} ${isSelected ? styles.selectedDevice : ''}`}
                    onClick={() => patch({
                      selectedDevice: deviceKey,
                      audio_device: device.name,
                      channel: device.channel ?? 0,
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
            )
            })}
            
            </div>
          </div>
        )}


        {/* Step 3 */}
        {step === 2 &&(

          <div className={styles.stepContent}>
            <div className={styles.instrumentNameInput}>
              <label>Instrument name</label>
              <input 
                type="text" 
                placeholder='vocals, guitar, piano, synthesizer'
                maxLength={24}
                value={formData.name}
                onChange={e => {
                // replace spaces with underscores, lowercase, strip special chars
                const cleaned = e.target.value
                  .toLowerCase()
                  .replace(/\s+/g, '_')
                  .replace(/[^a-z0-9_]/g, '');
                patch({ name: cleaned });
                }}
              /> 
            </div>

            <div className={styles.modelSelection}>
              <label>
                Select analysers
              </label>
              <div className={styles.modelCards}>

              {AVAILABLE_MODELS.map((model) => {
                const isSelected = formData.models.includes(model.id);
                return (
                  <button
                  key={model.id}
                  className={`${styles.modelCard} ${isSelected ? styles.selectedCard : ''}`}
                  onClick={() => patch({
                    models: isSelected
                    ? formData.models.filter(m => m !== model.id)
                    : [...formData.models, model.id]
                  })}
                  onMouseEnter={() => setHoveredModel(model)}
                  onMouseLeave={() => setHoveredModel(null)}
                  >
                    <span className={styles.modelName}>{model.id}</span>
                  </button>
                );
              })}
              </div>
              <div className={styles.modelDescription}>
                {hoveredModel && (
                  <p>{hoveredModel.explenation}</p>
                )}
              </div>
              
            </div>
                        
          </div>
        )}


        {/* Step 4 */}
        {step === 3 &&(
          <div className={styles.stepContent}>
            <p>Step 3 content goes here...</p>
          </div>
        )}

        {/* Navigation */}
        <div className={styles.navigation}>
          
          {/* go back to previous step */}
          <button
            className={styles.backButton}
            onClick={() => setStep(s => s - 1)}
            style={{ visibility: step > 0 ? 'visible' : 'hidden' }}
          >
            Back
          </button>
        
          <p className={styles.navText}>Step {step + 1} of {STEP_LABELS.length}</p>
          <button className={styles.nextBtn}
            onClick={() =>  {console.log('[FormData]', formData); step < STEP_LABELS.length - 1 ? setStep(s => s + 1) : onSubmit(formData)}}
            disabled={!canContinue}
          >
            {step < STEP_LABELS.length - 1 ? 'Continue →' : 'Add instrument'}
          </button>
        </div>


      </div>
    </div>
  );
};

export default AddInstrumentModal;