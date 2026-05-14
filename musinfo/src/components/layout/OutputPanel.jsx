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
            // Pattern B: /analyser/instrument/subkey  (e.g. /dynamics/piano/rms, /mood/mix/top)
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

                const parsedPayload = payload;

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

                // Reset onset pulse after 150ms so it flashes rather than staying lit
                if (subkey === 'onset') {
                    setTimeout(() => {
                        setAnalyserData(prev => ({
                            ...prev,
                            [instrument]: {
                                ...prev[instrument],
                                [analyser]: {
                                    ...prev[instrument]?.[analyser],
                                    onset: '0'
                                }
                            }
                        }));
                    }, 150);
                }
            }
        });

        return () => { unlisten.then(fn => fn()); };
    }, []);

    // ── Renderers ────────────────────────────────────────────────────────────

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
                {top              && <div>mood: {top}</div>}
                {danceability != null && <div>danceability: {danceability}%</div>}
                {tags             && <div>tags: {tags}</div>}
                
            </div>
        );
    };
    

    const renderBpm = (bpmData) => {
        if (!bpmData) return '—';
        const { estimation, accurate } = bpmData;
        return (
            <div>
                {estimation != null && <div>estimation: {estimation} bpm</div>}
                {accurate   != null && <div>accurate: {accurate} bpm</div>}
            </div>
        );
    };

    const renderDynamics = (dynamicsData) => {
        if (!dynamicsData) return '—';
        const { rms, onset, onset_strength, rms_at_onset } = dynamicsData;
        const rmsValue = Number(rms);
        const rmsDisplay = rmsValue < 0.01 ? 0.0 : rmsValue;
        return (
            <div>
                {rms            != null && <div>amplitude: {rmsDisplay.toFixed(1)}</div>}
                {onset          != null && <div>onset: {Number(onset) === 1 ? '▮' : '·'}</div>}
                {onset_strength != null && <div>strength: {Number(onset_strength).toFixed(3)}</div>}
                {rms_at_onset   != null && <div>rms@onset: {Number(rms_at_onset).toFixed(1)}</div>}
            </div>
        );
    };

    // Safe fallback — always converts to string, never passes an object to JSX
    const renderValue = (analyser, instrument) => {
        const data = analyserData[instrument]?.[analyser];
        if (analyser === 'genre')    return renderGenre(data);
        if (analyser === 'mood')     return renderMood(data);
        if (analyser === 'bpm')      return renderBpm(data);
        if (analyser === 'dynamics') return renderDynamics(data);
        if (analyser === 'pitch_crepe') return data != null ? String(data) : '—';
        // Default: always stringify — prevents any object from slipping through to JSX
        return data != null ? String(data) : '—';
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