import React from 'react';
import AudioDevices from './audio-devices/AudioDevices';
import AnalyserConfig from './analyser-config/AnalyserConfig';
import styles from './Setup.module.css';

const Setup = () => {
    return (
        <div className={styles.setup}>
            <AudioDevices />
            <AnalyserConfig/>
            {/* Empty component */}
        </div>
    );
};

export default Setup;