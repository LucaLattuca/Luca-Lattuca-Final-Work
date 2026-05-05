import React, {useState, useEffect} from 'react';

import styles from './Setup.module.css';

import InstrumentConfig   from '../../shared/InstrumentConfig/InstrumentConfig';
import AudioDevicesConfig from '../../shared/AudioDevicesConfig/AudioDevicesConfig';
import AnalyserConfig     from '../../shared/AnalyserConfig/AnalyserConfig';
import SignalPath         from '../../shared/SignalPath/SignalPath';
import TestAudio          from '../../shared/TestAudio/TestAudio';
import TestMidi           from '../../shared/TestMIDI/TestMidi';

const Setup = ({
    selectedInstrument,
    switchInstrument,
    instruments,
    onUpdateInstrument,
    onSwapDevices,
    onReconcile,
    onDeleteInstrument,
}) => {

    const [formData, setFormData] = useState(null);
    const [deleteInstrumentPrompt,  setDeleteInstrumentPrompt]  = useState(null);


    const confirmDelete = () => {
      if (!deleteInstrumentPrompt) return;
      onDeleteInstrument(formData.name);
      setDeleteInstrumentPrompt(null);
    };

    // Tracks current instrument in instruments.json
    const [savedInstrumentKey, setSavedInstrumentKey] = useState(null);

    useEffect(() => {
        if (selectedInstrument) {
          setFormData({ ...selectedInstrument });
          setSavedInstrumentKey(selectedInstrument.name);
        }
    }, [switchInstrument]);


    const patch = (fields) =>
    setFormData(prev => ({ ...prev, ...fields }));


    const save = (fields) => {
        if (fields.name === '') return; 
        setFormData(prev => {
          const updated = { ...prev, ...fields };

          // disable mix when no anlysers are selected
          if (isMix && fields.analysers !== undefined) {
            updated.enabled = fields.analysers.length > 0;
          }

          onUpdateInstrument(savedInstrumentKey, updated);
          return updated;
        });
        // keep originalName in sync so the next save uses the correct key
        if (fields.name && fields.name !== savedInstrumentKey) {
          setSavedInstrumentKey(fields.name);
        }
    };

    const handleSwapDevice = (otherName, newDevice) => {
      const myCurrentDevice = formData.audio_device;
      patch({ audio_device: newDevice });
      onSwapDevices(formData.name, newDevice, otherName, myCurrentDevice);
    };

    // handles source change for mix instrument
    const handleSourceChange = (source) => {
      if (source === 'internal') {
        // Switch to internal: remove audio_device, add source_instruments
        const allInstruments = Object.keys(instruments).filter(name => 
          instruments[name].type !== 'mix'
        );

        // Create new object without audio_device
        const { audio_device, ...cleanData } = formData;

        const updated = {
          ...cleanData,
          mix_source: 'internal',
          source_instruments: allInstruments
        };

        // Update state and save
        setFormData(updated);
        onUpdateInstrument(savedInstrumentKey, updated);

      } else if (source === 'external') {
        // Switch to external: just change source, audio_device added when device selected
        const updated = {
          ...formData,
          mix_source: 'external'
        };

        setFormData(updated);
        onUpdateInstrument(savedInstrumentKey, updated);
      }
    };

    if (!formData) return <div className={styles.setup}><p>Add an instrument to continue.</p></div>;

    // check if selected instrument is a mix
    const isMix = formData.type === 'mix';
    const isInternalMix = formData.mix_source === 'internal';

    return (
      <div className={styles.setup}>
        
        {/* Delete modal - only show for regular instruments */}
        {deleteInstrumentPrompt && !isMix && (
          <div className={styles.deleteOverlay}>
            <div className={styles.deleteModal}>
              <p className={styles.deleteTitle}>Delete <strong>{formData.name}</strong>?</p>
              <p className={styles.deleteDetail}>This cannot be undone.</p>
              <div className={styles.deleteActions}>
                <button className={styles.deleteCancel} onClick={() => setDeleteInstrumentPrompt(null)}>
                  Cancel
                </button>
                <button className={styles.deleteConfirm} onClick={confirmDelete}>
                  Delete
                </button>
              </div>
            </div>
          </div>
        )}
    
        {/* MIX CONFIGURATION */}
        {isMix ? (
          <>
            {/* Mix Header */}
            <div className={styles.mixHeader}>
              <p className={styles.mixDescription}>Combines multiple instruments for full-mix analysis</p>
            </div>
        
            {/* Source selector */}
            <div className={styles.sourceSelector}>
              <label>Mix Source</label>
              <div className={styles.sourceOptions}>
                <button
                  className={`${styles.sourceOption} ${isInternalMix ? styles.selected : ''}`}
                  onClick={() => handleSourceChange('internal')}
                >
                  Internal
                </button>
                <button
                  className={`${styles.sourceOption} ${!isInternalMix ? styles.selected : ''}`}
                  onClick={() => handleSourceChange('external')}
                >
                  External
                </button>
              </div>
            </div>
            
            {!isInternalMix && (
              <div className={styles.deviceSelector}>
                <AudioDevicesConfig
                  inputType="all"
                  selectedDevice={formData.audio_device}
                  onSelectDevice={(device) => save({ audio_device: device })}
                  onSwapDevice={null}
                  currentInstrumentName={formData.name}
                  allInstruments={instruments}
                  onReconcile={onReconcile}
                />
              </div>
            )}
        
            <div className={styles.analyserSelector}>
              <AnalyserConfig
                selectedAnalysers={formData.analysers}
                onAnalysersChange={(analysers) => save({ analysers })}
              />
              {formData.analysers.length === 0 && (
                <p className={styles.disabledWarning}>
                  ⚠ Mix is disabled. Select at least one analyser to enable.
                </p>
              )}
            </div>
            {/* add signal path */}
          </>
        ) : (
          /* REGULAR INSTRUMENT CONFIGURATION */
          <>
            <div className={styles.instrumentControls}>
              <InstrumentConfig
                name={formData.name}
                type={formData.type}
                showName={true}
                showType={true}
                onNameChange={(n) => save({ name: n })}
                onTypeChange={(t) => patch({ type: t })}
              />
              {/* Guard testaudio */}
              { formData.type === 'midi'
                 ? <TestMidi deviceName={formData.midi_device?.name} />
                 : <TestAudio deviceId={formData.audio_device?.device_id} channel={formData.audio_device?.channel} />
              }
            </div>
        
            <div className={styles.audioControls}>
              <AudioDevicesConfig
                inputType={formData.type}
                selectedDevice={formData.type === 'midi' ? formData.midi_device : formData.audio_device}
                onSelectDevice={(device) => {
                  if (formData.type === 'midi') {
                    const midiDevice = { name: device.name, device_id: device.index, port: 'input', connected: true };
                    patch({ midi_device: midiDevice, audio_device: undefined });
                    save({ midi_device: midiDevice, audio_device: undefined });
                  } else {
                    save({ audio_device: device, midi_device: undefined });
                  }
                }}
                onSwapDevice={formData.type === 'midi' ? null : handleSwapDevice}
                currentInstrumentName={formData.name}
                allInstruments={instruments}
                onReconcile={onReconcile}
              />
              <AnalyserConfig
                selectedAnalysers={formData.analysers}
                onAnalysersChange={(analysers) => save({ analysers })}
              />
            </div>
        
            <div className={styles.setupFooter}>
              <div className={styles.signalPath}>
                <SignalPath
                  name={formData.name}
                  audioDevice={formData.type !== 'midi' ? formData.audio_device : null}
                  analysers={formData.analysers}
                />
              </div>
              <div className={styles.removeInstrument}>
                <button onClick={() => setDeleteInstrumentPrompt(true)}>Delete instrument</button>
              </div>
            </div>
          </>
        )}
    
      </div>
    );
};

export default Setup;