import React, {useState, useEffect} from 'react';

import styles from './Setup.module.css';

import InstrumentConfig   from '../../shared/InstrumentConfig/InstrumentConfig';
import AudioDevicesConfig from '../../shared/AudioDevicesConfig/AudioDevicesConfig';
import AnalyserConfig     from '../../shared/AnalyserConfig/AnalyserConfig';
import SignalPath         from '../../shared/SignalPath/SignalPath';
import TestAudio          from '../../shared/TestAudio/TestAudio';


const Setup = ({
    selectedInstrument,
    switchInstrument,
    instruments,
    onUpdateInstrument,
    onSwapDevices,
    onReconcile,
}) => {

    const [formData, setFormData] = useState(null);

    // Tracks current instrument in instruments.json
    const [savedInstrumentKey, setSavedInstrumentKey] = useState(null);

    useEffect(() => {
        if (selectedInstrument) {
          setFormData({ ...selectedInstrument });
          setSavedInstrumentKey(selectedInstrument.name);
        }
    }, [switchInstrument]);


    const patch = (fields) =>
    setFormData(prev => ({ ...prev, ...fields }));


    const save = (fields) => {
        if (fields.name === '') return; 
        setFormData(prev => {
          const updated = { ...prev, ...fields };
          onUpdateInstrument(savedInstrumentKey, updated);
          return updated;
        });
        // keep originalName in sync so the next save uses the correct key
        if (fields.name && fields.name !== savedInstrumentKey) {
          setSavedInstrumentKey(fields.name);
        }
    };

    const handleSwapDevice = (otherName, newDevice) => {
      const myCurrentDevice = formData.audio_device;
      patch({ audio_device: newDevice });
      onSwapDevices(formData.name, newDevice, otherName, myCurrentDevice);
    };


    if (!formData) return <div className={styles.setup}><p>Add an instrument to continue.</p></div>;


    return (
        <div className={styles.setup}>

            <div className={styles.instrumentControls}>
              <InstrumentConfig
                name={formData.name}
                type={formData.type}
                showName={true}
                showType={true}
                onNameChange={(n) => save({ name: n })}   // instant save → sidebar updates live
                onTypeChange={(t) => patch({ type: t })}  // local only until a device is selected
              />
              <TestAudio
                deviceId={formData.audio_device.device_id}
                channel={formData.audio_device.channel}
              />
            </div>

            <div className={styles.audioControls}>
              <AudioDevicesConfig
                inputType={formData.type}
                selectedDevice={formData.audio_device}
                onSelectDevice={(device) => save({ audio_device: device })} // also flushes pending type
                onSwapDevice={handleSwapDevice}
                currentInstrumentName={formData.name}
                allInstruments={instruments}
                onReconcile={onReconcile} 
              />
              <AnalyserConfig
                selectedModels={formData.models}
                onModelsChange={(models) => save({ models })} // instant save
              />
            </div>

            <div className={styles.signalPath}>
              <SignalPath
                name={formData.name}
                audioDevice={formData.audio_device}
                models={formData.models}
              />
            </div>

        </div>
    );
};

export default Setup;