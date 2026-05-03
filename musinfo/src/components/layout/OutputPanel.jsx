import React, { useEffect, useState } from 'react';
import { listen } from '@tauri-apps/api/event';
import styles from './OutputPanel.module.css';


const OutputPanel = ({
    instruments = []
}) => {
    // Store latest value for each instrument/analyser combo
    // Format: { "vocals": { "pitch": "A4 (440.0Hz)", "genre": [...] }, ... }
    const [analyserData, setAnalyserData] = useState({});
    
    const output = Object.entries(instruments);

    useEffect(() => {
        console.log('[OutputPanel] Setting up OSC listener...');
        
        // Listen for OSC messages from the backend
        const unlisten = listen('osc-message', (event) => {
            console.log('[OutputPanel] OSC received:', {
                address: event.payload.address,
                payload: event.payload.payload,
                payloadType: typeof event.payload.payload
            });
            
            // event.payload is { address: "/pitch/vocals", payload: "A4 (440.0Hz)" }
            const { address, payload } = event.payload;
            
            // Parse address: "/pitch/vocals" -> analyser="pitch", instrument="vocals"
            const parts = address.split('/').filter(Boolean);
            if (parts.length === 2) {
                const [analyser, instrument] = parts;
                
                console.log('[OutputPanel] Parsed:', { analyser, instrument, payload });
                
                // Try to parse JSON for genre data
                let parsedPayload = payload;
                if (analyser === 'genre') {
                    try {
                        parsedPayload = JSON.parse(payload);
                        console.log('[OutputPanel] Genre data parsed:', parsedPayload);
                    } catch (e) {
                        console.warn('[OutputPanel] Failed to parse genre JSON:', payload, e);
                    }
                }
                
                setAnalyserData(prev => {
                    const updated = {
                        ...prev,
                        [instrument]: {
                            ...prev[instrument],
                            [analyser]: parsedPayload
                        }
                    };
                    console.log('[OutputPanel] State updated:', updated);
                    return updated;
                });
            } else {
                console.warn('[OutputPanel] Invalid address format:', address);
            }
        });

        return () => {
            console.log('[OutputPanel] Cleaning up OSC listener...');
            unlisten.then(fn => fn());
        }
    }, []);

    // Render genre data (array of top 3)
    const renderGenre = (genreData) => {
        if (!Array.isArray(genreData)) {
            return genreData || "—";
        }
        
        return (
            <div className={styles.genreList}>
                {genreData.map((item, idx) => (
                    <div key={idx} className={styles.genreItem}>
                        <span className={styles.genreName}>{item.genre}</span>
                        <span className={styles.genreConfidence}>{item.confidence}%</span>
                    </div>
                ))}
            </div>
        );
    };

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
                                    {analyser === 'genre' 
                                        ? renderGenre(analyserData[name]?.[analyser])
                                        : (analyserData[name]?.[analyser] || "—")
                                    }
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