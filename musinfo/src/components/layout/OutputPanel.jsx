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
            // Pattern B: /analyser/instrument/subkey  (e.g. /dynamics/piano/rms, /tempo/mix/pulse)
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

                // harmony/frontend arrives as a JSON string
                if (analyser === 'harmony' && subkey === 'frontend') {
                    try { parsedPayload = JSON.parse(payload); } catch (e) {}
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

                // Flash-and-clear for trigger-style subkeys (onset, pulse, attack).
                // After 150ms reset to '0' so the dot disappears and reappears on next beat.
                if (subkey === 'onset' || subkey === 'pulse' || subkey === 'attack') {
                    setTimeout(() => {
                        setAnalyserData(prev => ({
                            ...prev,
                            [instrument]: {
                                ...prev[instrument],
                                [analyser]: {
                                    ...prev[instrument]?.[analyser],
                                    [subkey]: '0'
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
    

    const renderTempo = (tempoData) => {
        if (!tempoData) return '—';
        const { bpm, bpm_accurate, feel, pulse } = tempoData;
        return (
            <div>
                {pulse        != null && <div>pulse: {Number(pulse) === 1 ? '●' : '○'}</div>}
                {bpm          != null && <div>bpm: {bpm}</div>}
                {bpm_accurate != null && <div>bpm (accurate): {bpm_accurate}</div>}
                {feel         != null && <div>feel: {feel}</div>}
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

    const renderTimbre = (timbreData) => {
        if (!timbreData) return '—';
        const { centroid, flux, flatness, rolloff, mfcc_delta, attack } = timbreData;
        return (
            <div>
                {centroid   != null && <div>brightness: {Number(centroid).toFixed(0)} Hz</div>}
                {rolloff    != null && <div>weight: {Number(rolloff).toFixed(0)} Hz</div>}
                {flatness   != null && <div>tonal/noisy: {Number(flatness).toFixed(3)}</div>}
                {flux       != null && <div>busyness: {Number(flux).toFixed(3)}</div>}
                {mfcc_delta != null && <div>change: {Number(mfcc_delta).toFixed(3)}</div>}
                {attack     != null && <div>attack: {Number(attack) === 0 ? '·' : `${(Number(attack) * 1000).toFixed(0)}ms ▮`}</div>}
            </div>
        );
    };

    const renderHarmony = (harmonyData) => {
        if (!harmonyData) return '—';
        
        // harmony arrives as a JSON string on the /frontend address
        let data = harmonyData;
        if (typeof data === 'string') {
            try { data = JSON.parse(data); } catch (e) { return String(harmonyData); }
        }

        const { chord, root, relation_to_root, chord_quality, dissonance, key } = data;

        return (
            <div>
                {chord            != null && <div>chord: {chord}</div>}
                {root             != null && <div>root: {root}</div>}
                {chord_quality    != null && <div>quality: {chord_quality}</div>}
                {relation_to_root != null && <div>degree: {relation_to_root}</div>}
                {key              != null && <div>key: {key}</div>}
                {dissonance       != null && <div>dissonance: {Number(dissonance).toFixed(2)}</div>}
            </div>
        );
    };


    // Safe fallback — always converts to string, never passes an object to JSX
    const renderValue = (analyser, instrument) => {
        const data = analyserData[instrument]?.[analyser];
        if (analyser === 'genre')    return renderGenre(data);
        if (analyser === 'mood')     return renderMood(data);
        if (analyser === 'tempo')    return renderTempo(data);
        if (analyser === 'dynamics') return renderDynamics(data);
        if (analyser === 'timbre')   return renderTimbre(data);
        if (analyser === 'harmony')  return renderHarmony(data?.frontend);
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