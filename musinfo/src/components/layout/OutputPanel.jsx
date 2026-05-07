import React, { useEffect, useState } from 'react';
import { listen } from '@tauri-apps/api/event';
import styles from './OutputPanel.module.css';


const OutputPanel = ({
    instruments = []
}) => {
    const [analyserData, setAnalyserData] = useState({});
    
    const output = Object.entries(instruments);

    useEffect(() => {
        const unlisten = listen('osc-message', (event) => {
            console.log('[OutputPanel] OSC received:', event.payload);
            
            const { address, payload } = event.payload;
            const parts = address.split('/').filter(Boolean);

            // Pattern A: /analyser/instrument         (e.g. /genre/vocals, /pitch/vocals)
            // Pattern B: /analyser/instrument/subkey  (e.g. /mood/backing_track/top)
            if (parts.length === 2) {
                const [analyser, instrument] = parts;

                let parsedPayload = payload;
                if (analyser === 'genre') {
                    try { parsedPayload = JSON.parse(payload); } catch (e) {}
                }

                setAnalyserData(prev => ({
                    ...prev,
                    [instrument]: {
                        ...prev[instrument],
                        [analyser]: parsedPayload
                    }
                }));

            } else if (parts.length === 3) {
                const [analyser, instrument, subkey] = parts;

                let parsedPayload = payload;
                if (analyser === 'mood' && subkey === 'tags') {
                    // tags arrive as "film, dark" — keep as string, split for display
                    parsedPayload = payload;
                }

                setAnalyserData(prev => ({
                    ...prev,
                    [instrument]: {
                        ...prev[instrument],
                        [analyser]: {
                            ...prev[instrument]?.[analyser],
                            [subkey]: parsedPayload
                        }
                    }
                }));
            }
        });

        return () => { unlisten.then(fn => fn()); };
    }, []);

    const renderGenre = (genreData) => {
        if (!Array.isArray(genreData)) return String(genreData ?? '—');
        return (
            <div>
                {genreData.map((item, idx) => (
                    <div key={idx}>{item.genre} ({item.confidence}%)</div>
                ))}
            </div>
        );
    };

    const renderMood = (moodData) => {
        if (!moodData) return '—';
        const { top, danceability, tags } = moodData;
        return (
            <div>
                {top         && <div>mood: {top}</div>}
                {danceability != null && <div>danceability: {danceability}%</div>}
                {tags        && <div>tags: {tags}</div>}
            </div>
        );
    };

    const renderValue = (analyser, instrument) => {
        const data = analyserData[instrument]?.[analyser];
        if (analyser === 'genre') return renderGenre(data);
        if (analyser === 'mood')  return renderMood(data);
        return data || '—';
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
                                    {renderValue(analyser, name)}
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