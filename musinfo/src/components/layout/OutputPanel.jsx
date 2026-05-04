import React, { useEffect, useState } from 'react';
import { listen } from '@tauri-apps/api/event';
import styles from './OutputPanel.module.css';


const OutputPanel = ({
    instruments = []
}) => {
    // Store latest value for each instrument/analyser combo
    // Format: { "vocals": { "pitch": "A4 (440.0Hz)", "genre": [{genre: "Folk", confidence: 67.3}, ...] } }
    const [analyserData, setAnalyserData] = useState({});
    
    const output = Object.entries(instruments);

    useEffect(() => {
        // Listen for OSC messages from the backend
        const unlisten = listen('osc-message', (event) => {
            console.log('[OutputPanel] OSC received:', event.payload);
            
            // event.payload is { address: "/pitch/vocals", payload: "A4 (440.0Hz)" }
            const { address, payload } = event.payload;
            
            // Parse address: "/pitch/vocals" -> analyser="pitch", instrument="vocals"
            const parts = address.split('/').filter(Boolean);
            if (parts.length === 2) {
                const [analyser, instrument] = parts;
                
                // Parse genre JSON if applicable
                let parsedPayload = payload;
                if (analyser === 'genre') {
                    try {
                        parsedPayload = JSON.parse(payload);
                        console.log('[OutputPanel] Parsed genre data:', parsedPayload);
                    } catch (e) {
                        console.error('[OutputPanel] Failed to parse genre JSON:', e);
                    }
                }
                
                console.log('[OutputPanel] Updating:', { instrument, analyser, parsedPayload });
                
                setAnalyserData(prev => ({
                    ...prev,
                    [instrument]: {
                        ...prev[instrument],
                        [analyser]: parsedPayload
                    }
                }));
            }
        });

        return () => {
            unlisten.then(fn => fn());
        }
    }, []);

    // Render genre data (array of {genre, confidence})
    const renderGenre = (genreData) => {
        if (!Array.isArray(genreData)) return String(genreData);
        
        return (
            <div>
                {genreData.map((item, idx) => (
                    <div key={idx}>
                        {item.genre} ({item.confidence}%)
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
                                        ? renderGenre(analyserData[name]?.genre)
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