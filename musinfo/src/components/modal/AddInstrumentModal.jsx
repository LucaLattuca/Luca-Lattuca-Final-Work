import React, { useState } from 'react';
import styles from './AddInstrumentModal.module.css';


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



const AddInstrumentModal = ({ onClose, onSubmit }) => {
  const [step, setStep] = useState(0);
  // instrument object to update instruments.json with
  const [formData, setFormData] = useState({
    name: '',
    audio_device: '',
    channel: 0,
    models: [],
  });



  // update fields
  const patch = (fields) => setFormData(prev => ({ ...prev, ...fields }));
  // prevent going to next step if required fields are not filled
  const canContinue = step === 0 ? !!formData.type : true;


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
              {/* todo add description at bottom */}
          </div>
        )}
  
        {/* Step 2 */}
        {step === 1 &&(
          <div className={styles.stepContent}>
            <p>Step 2 content goes here...</p>
          </div>
        )}

        {/* Step 3 */}
        {step === 2 &&(
          <div className={styles.stepContent}>
            <p>Step 3 content goes here...</p>
          </div>
        )}

        {/* Step 2 */}
        {step === 3 &&(
          <div className={styles.stepContent}>
            <p>Step 4 content goes here...</p>
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
            onClick={() => step < STEP_LABELS.length - 1 ? setStep(s => s + 1) : onSubmit(formData)}
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