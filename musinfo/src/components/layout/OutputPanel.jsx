import React, { useEffect, useState } from 'react';
import { listen } from '@tauri-apps/api/event';
import styles from './OutputPanel.module.css';


const OutputPanel = ({
    instruments = []
}) => {
    const [messages, setMessages] = useState([]);
    
    const output = Object.entries(instruments);

    useEffect(()=> {

        // Listen for/Subscribe to OSC messages from the backend
        const unlisten = listen('osc-message', (event) => {
            const timestamp = new Date().toLocaleTimeString();
            setMessages(prev => [
                { id: Math.random(), text: event.payload, timestamp: timestamp },
                ...prev
            ]);
        });

        // cleanup lisner when component unmounts
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
                            {(config.models ?? []).map(model => (
                                <div key={model} className={styles.analyserRow}>
                                    <span className={styles.analyserName}>{model}:</span>
                                    <span className={styles.analyserValue}>—</span>
                                </div>
                            ))}
                        </div>
                    </div>
                ))}
    </div>
  );
};

export default OutputPanel;