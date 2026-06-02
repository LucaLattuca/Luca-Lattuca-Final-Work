import React, { useState } from 'react';
import styles from './AddInstrumentModal.module.css';

import InstrumentConfig   from '../shared/InstrumentConfig/InstrumentConfig';
import AudioDevicesConfig from '../shared/AudioDevicesConfig/AudioDevicesConfig';
import AnalyserConfig     from '../shared/AnalyserConfig/AnalyserConfig';
import SignalPath         from '../shared/SignalPath/SignalPath';
import TestAudio          from '../shared/TestAudio/TestAudio';
import TestMidi           from '../shared/TestMIDI/TestMidi';

const STEP_LABELS = ['Choose input type', 'Select device', 'Configure', 'Test signal'];

const AddInstrumentModal = ({ onClose, onSubmit, instruments }) => {

  const [step, setStep] = useState(0);

  const [formData, setFormData] = useState({
    name:     '',
    role:     '',
    enabled:  true,
    type:     '',
    audio_device: {
      name:               '',
      device_id:          null,
      host_api:           '',
      max_input_channels: 0,
      channel:            0,
      sample_rate:        0,
    },
    analysers: [],
  });

  const patch = (fields) => setFormData(prev => ({ ...prev, ...fields }));

  const canContinue =
    step === 0 ? !!formData.type :
    step === 1 ? (formData.type === 'midi' ? !!formData.midi_device?.name : !!formData.audio_device?.name) :
    step === 2 ? formData.analysers.length > 0 && !!formData.name && !!formData.role :
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

        {/* Step 1 — input type */}
        {step === 0 && (
          <div className={styles.stepContent}>
            <InstrumentConfig
              variant="modal"
              type={formData.type}
              onTypeChange={(t) => patch({ type: t })}
              showName={false}
              showRole={false}
            />
          </div>
        )}

        {/* Step 2 — device selection */}
        {step === 1 && (
          <div className={styles.stepContent}>
            <AudioDevicesConfig
              inputType={formData.type}
              selectedDevice={formData.type === 'midi' ? formData.midi_device : formData.audio_device}
              onSelectDevice={(device) => {
                if (formData.type === 'midi') {
                  patch({ midi_device: { name: device.name, device_id: device.index, port: 'input', connected: true } });
                } else {
                  patch({ audio_device: device });
                }
              }}
              currentInstrumentName=""
              allInstruments={instruments}
            />
          </div>
        )}

        {/* Step 3 — name, role, analysers */}
        {step === 2 && (
          <div className={styles.stepContent}>
            <InstrumentConfig
              variant="modal"
              name={formData.name}
              onNameChange={(n) => patch({ name: n })}
              role={formData.role}
              onRoleChange={(r) => patch({ role: r })}
              showType={false}
            />
            <AnalyserConfig
              variant="modal"
              selectedAnalysers={formData.analysers}
              onAnalysersChange={(analysers) => patch({ analysers })}
            />
          </div>
        )}

        {/* Step 4 — test signal */}
        {step === 3 && (
          <div className={styles.stepContent}>
            {formData.type !== 'midi' && (
              <TestAudio
                deviceId={formData.audio_device.device_id}
                channel={formData.audio_device.channel}
              />
            )}
            {formData.type === 'midi' && (
              <TestMidi deviceName={formData.midi_device?.name} />
            )}
            <div className={styles.finalConfigSection}>
              <SignalPath
                name={formData.name}
                audioDevice={formData.type !== 'midi' ? formData.audio_device : null}
                analysers={formData.analysers}
              />
            </div>
          </div>
        )}

        {/* Navigation */}
        <div className={styles.navigation}>
          <button
            className={styles.backButton}
            onClick={() => setStep(s => s - 1)}
            style={{ visibility: step > 0 ? 'visible' : 'hidden' }}
          >
            Back
          </button>
          <p className={styles.navText}>Step {step + 1} of {STEP_LABELS.length}</p>
          <button
            className={styles.nextButton}
            onClick={() => {
              console.log('[FormData]', formData);
              step < STEP_LABELS.length - 1 ? setStep(s => s + 1) : onSubmit(formData);
            }}
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