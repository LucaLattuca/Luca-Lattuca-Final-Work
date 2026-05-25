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

const Performance = ({ setForcedKey }) => {
  const [enabled, setEnabled]       = useState(false);
  const [selectedKey, setSelectedKey] = useState(null);

  const handleToggleEnable = () => {
    const next = !enabled;
    setEnabled(next);
    if (!next) {
      setSelectedKey(null);
      setForcedKey({ enabled: false, key: null });
      invoke('save_performance_config', { enabled: false, key: null });
    } else {
      setForcedKey({ enabled: true, key: selectedKey });
      invoke('save_performance_config', { enabled: true, key: selectedKey });
    }
  };

  const handleKeySelect = (key) => {
    const next = selectedKey === key ? null : key;
    setSelectedKey(next);
    if (enabled) {
      setForcedKey({ enabled: true, key: next });
      invoke('save_performance_config', { enabled: true, key: next });
    }
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
              <span style={{ color: SCRIABIN_COLORS[selectedKey], fontWeight: 'bold' }}>
                {selectedKey}
              </span>
            )}
            
          </div>
            {!enabled && (
              <p className={Styles.infoText}>using automatic key detection according to harmony_analyser</p>
            )}
          <div className={Styles.keys}>
            <ul>
              {KEYS.map((key) => (
                <li key={key}>
                  <button
                    type="button"
                    onClick={() => handleKeySelect(key)}
                    style={{
                      borderColor: SCRIABIN_COLORS[key],
                      // dim the button when forced key is disabled
                      opacity: enabled ? 1 : 0,
                      // highlight the selected key
                      backgroundColor: selectedKey === key ? `${SCRIABIN_COLORS[key]}25` : 'transparent',
                      borderStyle: selectedKey === key ? `inset` : 'outset',
                    }}
                  >
                    {key}
                  </button>
                </li>
              ))}
            </ul>
          </div>

        </div>
      </div>
    </>
  );
};

export default Performance;