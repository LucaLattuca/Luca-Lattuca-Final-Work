import React, {useState, useEffect} from 'react';

import styles from './Setup.module.css';

import InstrumentConfig   from '../../shared/InstrumentConfig/InstrumentConfig';
import AudioDevicesConfig from '../../shared/AudioDevicesConfig/AudioDevicesConfig';
import AnalyserConfig     from '../../shared/AnalyserConfig/AnalyserConfig';
import SignalPath         from '../../shared/SignalPath/SignalPath';
import TestAudio          from '../../shared/TestAudio/TestAudio';


const Setup = ({ selectedInstrument }) => {

    const [formData, setFormData] = useState(null);

    useEffect(() => {
        if (selectedInstrument) setFormData({ ...selectedInstrument });
    }, [selectedInstrument]);

    const patch = (fields) => setFormData(prev => ({ ...prev, ...fields }));

    if (!formData) return <div className={styles.setup}><p>Add an instrument to continue.</p></div>;


    return (
        <div className={styles.setup}>
        <div className={styles.instrumentControls}>
           <InstrumentConfig
                name={formData.name}
                type={formData.type}
                showName={true}
                showType={true}
                onNameChange={(n) => patch({ name: n })}
                onTypeChange={(t) => patch({ type: t })}
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
                onSelectDevice={(device) => patch({ audio_device: device })}
                />

            <AnalyserConfig
                selectedModels={formData.models}
                onModelsChange={() => {}}
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