import React, { useEffect, useState } from 'react';
import { listen } from '@tauri-apps/api/event';
import styles from './OutputPanel.module.css';


const OutputPanel = ({
    instruments = []
}) => {
    // Store latest value for each instrument/analyser combo
    // Format: { "vocals": { "pitch": "A4 (440.0Hz)" }, "guitar": { "genre": "Folk (48.2%)" } }
    const [analyserData, setAnalyserData] = useState({});
    
    const output = Object.entries(instruments);

    useEffect(() => {
        // Listen for OSC messages from the backend
        const unlisten = listen('osc-message', (event) => {
            console.log('[OutputPanel] Full event:', JSON.stringify(event.payload, null, 2));
            
            // event.payload is now { address: "/pitch/vocals", payload: "A4 (440.0Hz)" }
            const { address, payload } = event.payload;
            
            // Parse address: "/pitch/vocals" -> analyser="pitch", instrument="vocals"
            const parts = address.split('/').filter(Boolean);
            if (parts.length === 2) {
                const [analyser, instrument] = parts;
                
                setAnalyserData(prev => ({
                    ...prev,
                    [instrument]: {
                        ...prev[instrument],
                        [analyser]: payload
                    }
                }));
            }
        });

        return () => {
            unlisten.then(fn => fn());
        }
    }, []);


    return (
        <div className={styles.outputPanel}>
            {output.length === 0 && (
                <p className={styles.empty}>No instruments configured.</p>
            )}

            {output.map(([name, config]) => (
                <div key={name} className={styles.instrument}>
                    <div className={styles.instrumentName}>{name}</div>

                    <div className={styles.analyserList}>
                        {(config.analysers ?? []).map(analyser => (
                            <div key={analyser} className={styles.analyserRow}>
                                <span className={styles.analyserName}>{analyser}:</span>
                                <span className={styles.analyserValue}>
                                    {analyserData[name]?.[analyser] || "—"}
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            ))}
        </div>
    );
};

export default OutputPanel;