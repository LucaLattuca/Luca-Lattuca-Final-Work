import React, { useState, useEffect } from 'react';
import styles from './AddInstrumentModal.module.css';
import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';



import InstrumentConfig   from '../shared/InstrumentConfig/InstrumentConfig';
import AudioDevicesConfig from '../shared/AudioDevicesConfig/AudioDevicesConfig';
import AnalyserConfig     from '../shared/AnalyserConfig/AnalyserConfig';
import SignalPath         from '../shared/SignalPath/SignalPath';


const STEP_LABELS = ['Choose input type', 'Select device', 'Configure', 'Test signal'];


const AddInstrumentModal = ({ onClose, onSubmit }) => {
  const [step, setStep] = useState(0);
  // instrument object to update instruments.json with
  const [formData, setFormData] = useState({
   name: '',
   enabled: true,
   type: '',
   audio_device: {
     name: '',
     device_id: null,
     host_api: '',
     max_input_channels: 0,
     channel: 0,
     sample_rate: 0,
   },
   models: [],
  });
  


  // audio test state
  const [isTesting, setIsTesting] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [peak, setPeak] = useState(0);

  // invoke Rust command to start audio testing in step 4
  useEffect(() => {
    if (step !== 3) return;

    let unlisten;

    const startListening = async () => {
      unlisten = await listen('test-audio-level', (event) => {
        const level = event.payload;
        setAudioLevel(level);
        setPeak(prev => Math.max(prev, level));
      });
    };

    startListening();

    // stop stream and unlisten when leaving step 4
    return () => {
      invoke('stop_device_test').catch(console.error);
      setIsTesting(false);
      setAudioLevel(0);
      setPeak(0);
      if (unlisten) unlisten();
    };
  }, [step]);

  // Test / stop audio test handler
  const handleTestToggle = async () => {
  if (isTesting) {
    await invoke('stop_device_test');
    setIsTesting(false);
  } else {
    await invoke('test_device_audio', {
      deviceId: formData.audio_device.device_id,
      channel: formData.audio_device.channel,
    });
    setIsTesting(true);
    setPeak(0);
  }
};


  // update fields
  const patch = (fields) => setFormData(prev => ({ ...prev, ...fields }));
  // prevent going to next step if required fields are not filled
  const canContinue = 
    step === 0 ? !!formData.type :
    step === 1 ? !!formData.audio_device.name :
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
            <InstrumentConfig
              type={formData.type}
              onTypeChange={(t) => patch({ type: t })}
              showName={false}
            />
          </div>
        )}
        
  
       

        {/* Step 2 : device selection */}
        {step === 1 &&(
          <div className={styles.stepContent}>
            <AudioDevicesConfig
              inputType={formData.type}
              selectedDevice={formData.audio_device}
              onSelectDevice={(device) => patch({ audio_device: device })}
            />
          </div>
        )}


        {/* Step 3 */}
        {step === 2 &&(
          <div className={styles.stepContent}>
            <InstrumentConfig
              name={formData.name}
              onNameChange={(n) => patch({ name: n })}
              showType={false}
            />
            <AnalyserConfig
              selectedModels={formData.models}
              onModelsChange={(models) => patch({ models })}
            />
          </div>
        )}


        {/* Step 4 */}
        {step === 3 && (
          <div className={styles.stepContent}>
          
            <div className={styles.testDevice}>
              <div className={styles.testControls}>
                <p>Live signal</p>
                <button
                  className={`${styles.testBtn} ${isTesting ? styles.testBtnActive : ''}`}
                  onClick={handleTestToggle}
                >
                  {isTesting ? 'Stop test' : 'Start test'}
                </button>
              </div>

              <div className={styles.testResult}>
                <div
                  className={`${styles.levelBar} ${audioLevel > 0.01 ? styles.levelBarActive : ''}`}
                  style={{ width: `${audioLevel * 100}%` }}
                />
              </div>
              
              <p className={styles.testMetrics}>
                RMS: {audioLevel.toFixed(3)} &nbsp;|&nbsp; Peak: {peak.toFixed(3)}
              </p>
            </div>
            <div className={styles.finalConfigSection}>

              <SignalPath
                name={formData.name}
                audioDevice={formData.audio_device}
                models={formData.models}
              />

              <p>Final check</p>
              <div className={styles.finalConfig}>
                <p><span>Name</span>{formData.name}</p>
                <p><span>Type</span>{formData.type}</p>
                <p><span>Device</span>{formData.audio_device.name}</p>
                <p><span>Channel</span>{formData.audio_device.channel}</p>
                <p><span>Host API</span>{formData.audio_device.host_api}</p>
                <p><span>Sample rate</span>{formData.audio_device.sample_rate} Hz</p>
                <p><span>Analysers</span>{formData.models.join(', ')}</p>
              </div>
            </div>

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