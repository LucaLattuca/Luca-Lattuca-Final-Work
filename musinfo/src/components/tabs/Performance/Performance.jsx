import React, { useState } from 'react';
import Styles from './Performance.module.css';
import { invoke } from '@tauri-apps/api/core';

// Alexander Scriabin's colour associations for each pitch class
const SCRIABIN_COLORS = {
  'C':     '#ff0000', // red
  'G':     '#ff8c00', // orange
  'D':     '#ffff00', // yellow
  'A':     '#148b14', // green
  'E':     '#669dfb', // sky blue
  'B':     '#3535ff', // blue
  'F#/Gb': '#00bfff', // bright blue
  'Db':    '#8000af', // violet / purple
  'Ab':    '#a675c7', // lilac
  'Eb':    '#a44a93', // flesh
  'Bb':    '#a8748e', // rose
  'F':     '#8b0027', // deep red
};

const KEYS = [ 'C','Db','D','Eb','E','F','F#/Gb','G','Ab','A','Bb','B'];

const Performance = ({ performanceState, setPerformanceState }) => {
  const { enabled, selectedKey, selectedScale } = performanceState;

  const setEnabled      = (v) => setPerformanceState(s => ({ ...s, enabled: v }));
  const setSelectedKey  = (v) => setPerformanceState(s => ({ ...s, selectedKey: v }));
  const setSelectedScale = (v) => setPerformanceState(s => ({ ...s, selectedScale: v }));

  const handleScaleSelect = (scale) => {
    setSelectedScale(scale);
    invoke('save_performance_config', { enabled, key: selectedKey, scale });
  };

  const handleToggleEnable = () => {
    const next = !enabled;
    setEnabled(next);
    if (!next) {
      invoke('save_performance_config', { enabled: false, key: null, scale: null })
        .catch(e => console.error('[save_performance_config] disable failed:', e));
    } else {
      invoke('save_performance_config', { enabled: true, key: selectedKey, scale: selectedScale })
        .catch(e => console.error('[save_performance_config] enable failed:', e));
    }
  };

  const handleKeySelect = (key) => {
    const next = selectedKey === key ? null : key;
    setSelectedKey(next);
    invoke('save_performance_config', { enabled, key: next, scale: selectedScale });
  };

  return (
    <>
      <div className={Styles.container}>
        <div className={Styles.forcedKey}>

          <div className={Styles.enableForcedKey}>
            <label>Forced Key</label>
            <button
              type="button"
              onClick={handleToggleEnable}
              style={{
                borderColor: enabled ? '#C70000 ' : '#30AE30',
              }}
            >
              {enabled ? 'Disable' : 'Enable'}
            </button>
            {enabled && selectedKey && (
              <>
                <span>
                  {selectedKey}
                </span>
                <span>
                  {selectedScale}
                </span>
              </>
            )}
            
          </div>
            {!enabled && (
              <p className={Styles.infoText}>using automatic key detection according to harmony_analyser</p>
            )}
            {enabled && (
              <p className={Styles.infoText}>using Forced key detection</p>
            )}
          <div className={Styles.harmonyConfig}>
            <div className={Styles.keys}>
              {!enabled && <div className={Styles.configVeil} />}
              <ul>
                {KEYS.map((key) => (
                  <li key={key}>
                    <button
                      type="button"
                      onClick={() => handleKeySelect(key)}
                      style={{
                        borderColor: SCRIABIN_COLORS[key],
                        backgroundColor: selectedKey === key ? `${SCRIABIN_COLORS[key]}25` : 'transparent',
                        borderStyle: selectedKey === key ? 'inset' : 'outset',
                      }}
                    >
                      {key}
                    </button>
                  </li>
                ))}
              </ul>
              <div className={Styles.scale}>
                  <>
                    <button
                      type="button"
                      onClick={() => handleScaleSelect('major')}
                      style={{ 
                        borderStyle: selectedScale === 'major' ? 'inset' : 'outset', 
                        borderColor: 'red',
                        backgroundColor: selectedScale === 'major' ? 'rgba(255,0,0,0.2)' : 'transparent',
                      }}
                      >
                      Major
                    </button>
                    <button
                      type="button"
                      onClick={() => handleScaleSelect('minor')}
                      style={{ 
                        borderStyle: selectedScale === 'minor' ? 'inset' : 'outset',
                        borderColor: 'blue',
                        backgroundColor: selectedScale === 'minor' ? 'rgba(0,0,255,0.2)' : 'transparent',
                      }}
                      >
                      Minor
                    </button>
                  </>
                
              </div>
            </div>
          </div>    


        </div>
      </div>
    </>
  );
};

export default Performance;