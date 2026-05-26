import React, { useState } from 'react';
import Styles from './Performance.module.css';
import { invoke } from '@tauri-apps/api/core';

import PianoKeyboard from '../Performance/PianoKeyboard/PianoKeyboard';


const Performance = ({ performanceState, setPerformanceState }) => {
  
  const { enabled, selectedKey, selectedScale, imageGenEnabled } = performanceState;


  const setEnabled      = (v) => setPerformanceState(s => ({ ...s, enabled: v }));
  const setSelectedKey  = (v) => setPerformanceState(s => ({ ...s, selectedKey: v }));
  const setSelectedScale = (v) => setPerformanceState(s => ({ ...s, selectedScale: v }));
  const setImageGenEnabled = (v) => setPerformanceState(s => ({ ...s, imageGenEnabled: v }));


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

  const handleImageGenToggle = () => {
    const next = !imageGenEnabled;
    setImageGenEnabled(next);
    invoke('toggle_image_generation', { enabled: next })
      .catch(e => console.error('[toggle_image_generation] failed:', e));
  };

  return (
    <>
      <div className={Styles.container}>
        <div className={Styles.forcedKeyConfig}>

          <div className={Styles.enableForcedKey}>
            
            <label>Forced Key</label>
            <button
              type="button"
              onClick={handleToggleEnable}
              className={Styles.toggleSwitch}
              style={{
                borderColor: enabled ? '#30AE30' : '#434343',
              }}
              data-enabled={enabled}

            />
             {!enabled && (
              <p className={Styles.infoText}>using automatic key detection through harmony analyser</p>
            )}
            {enabled && (
              <>
                <p className={Styles.infoText}>using Forced key detection, select your key and scale below</p>
                
              </>
            )}
            
            
          </div>
           
          <div className={Styles.configWrapper}>
              {!enabled && <div className={Styles.configVeil} />}
              <p className={Styles.currentKey}>Key : {selectedKey || 'C'} {selectedScale || 'Major'}</p>
              <div className={Styles.harmonyConfig}>
                <div>
                  <p>select key</p>
                  <PianoKeyboard selectedKey={selectedKey} onKeySelect={handleKeySelect} />
                </div>
                <div>
                      
                  <p>select scale</p>
                  <div className={Styles.scaleSelector}>
                      <button
                        type="button"
                        onClick={() => handleScaleSelect('major')}
                        style={{ 
                          borderStyle: selectedScale === 'major' ? 'inset' : 'outset', 
                        }}
                        >
                        Major
                      </button>
                      <button
                        type="button"
                        onClick={() => handleScaleSelect('minor')}
                        style={{ 
                          borderStyle: selectedScale === 'minor' ? 'inset' : 'outset',
                        }}
                        >
                        Minor
                      </button>
                  </div>
                </div>              
              </div>
          </div>    


        </div>
        <div className={Styles.imageGenerationConfig}>
          <label>Image Generation</label>
          <button
            type="button"
            onClick={handleImageGenToggle}
            className={Styles.toggleSwitch}
            style={{
              borderColor: imageGenEnabled ? '#30AE30' : '#434343',
            }}
            data-enabled={imageGenEnabled}
          />
        </div>

      </div>
    </>
  );
};

export default Performance;