import React from 'react';

import styles from './Setup.module.css';

import InstrumentConfig   from '../../shared/InstrumentConfig/InstrumentConfig';
import AudioDevicesConfig from '../../shared/AudioDevicesConfig/AudioDevicesConfig';
import AnalyserConfig     from '../../shared/AnalyserConfig/AnalyserConfig';
import SignalPath         from '../../shared/SignalPath/SignalPath';
import TestAudio          from '../../shared/TestAudio/TestAudio';


const Setup = ({ selectedInstrument }) => {

    if (!selectedInstrument) {
        return (
            <div className={styles.setup}>
                <p className={styles.hint}>Select an instrument from the sidebar.</p>
            </div>
        );
    }

    return (
        <div className={styles.setup}>
           <InstrumentConfig
                name={selectedInstrument.name}
                type={selectedInstrument.type}
                showName={true}
                showType={true}
                onNameChange={() => {}}
                onTypeChange={() => {}}
            />

            <AudioDevicesConfig
                inputType={selectedInstrument.type}
                selectedDevice={selectedInstrument.audio_device}
                onSelectDevice={() => {}}
            />

            <AnalyserConfig
                selectedModels={selectedInstrument.models}
                onModelsChange={() => {}}
            />

            <SignalPath
                name={selectedInstrument.name}
                audioDevice={selectedInstrument.audio_device}
                models={selectedInstrument.models}
            />

            <TestAudio
                deviceId={selectedInstrument.audio_device.device_id}
                channel={selectedInstrument.audio_device.channel}
            />
      
        </div>
    );
};

export default Setup;