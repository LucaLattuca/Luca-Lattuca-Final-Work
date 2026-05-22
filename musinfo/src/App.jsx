import reactLogo from "./assets/react.svg";
import { useState, useEffect, useRef  } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from '@tauri-apps/api/event';

import "./App.css";
import Layout from "./components/layout/Layout";
import AddInstrumentModal from "./components/modal/AddInstrumentModal";
import instrumentsConfig from "../backend/config/instruments.json";

function App() {

  const [pipelineStatus, setPipelineStatus] = useState('idle');

  const [instruments, setInstruments] = useState(instrumentsConfig.instruments);

  const prevMixConfig = useRef(null);

  // cache mix config
  useEffect(() => {
    if (instruments.mix) {
      prevMixConfig.current = instruments.mix;
    }
  }, [instruments]);
  
  // listen for current pipeline status
  useEffect(() => {
      const unlistenReady = listen('pipeline-ready', () => {
          setPipelineStatus('running');
      });

      return () => {
          unlistenReady.then(fn => fn());
      };
  }, []);

  // Switch instrument state
  const [switchInstrument, setSwitchInstrument] = useState(0);
  

    const handleStart = async () => {
    setPipelineStatus('launching');
    try {
      await invoke('start_pipeline');
    } catch (e) {
      console.error('[App] start_pipeline error:', e);
      setPipelineStatus('idle');
    }

  };

  const handleStop = async () => {
    setPipelineStatus('stopping');
    try {
      await invoke('stop_pipeline');
    } catch (e) {
      console.error('[App] stop_pipeline error:', e);
    } finally {
      setPipelineStatus('idle');
    }
  };

  // On launch, re-match device_ids by name + channel since hardware
  // indices can change between sessions. Marks devices as connected/disconnected.
  useEffect(() => {
      const reconcile = async () => {
          try {
              const updated = await invoke('reconcile_devices');
              const updatedInstruments = updated.instruments;
              setInstruments(updatedInstruments);
              // re-select the first instrument with the reconciled data
              const entries = Object.entries(updatedInstruments);
              if (entries.length > 0) {
                  const [name, data] = entries[0];
                  setSelectedInstrument({ name, ...data });
              }
          } catch (err) {
              console.error('[App] Failed to reconcile devices:', err);
          }
      };
      reconcile();
  }, []);

  useEffect(() => {
      // save session — entirely handled in Rust, nothing to do here yet
      const unlistenSave = listen('menu-save-session', () => {
          handleSaveSession();
      });

      // load session — Rust opens the picker, we just refresh the UI after
      const unlistenLoad = listen('menu-load-session', (event) => {
          handleLoadSession(event.payload);
      });

      // cleanup when App unmounts
      return () => {
          unlistenSave.then(fn => fn());
          unlistenLoad.then(fn => fn());
      };
  }, []);

  const handleSaveSession = async () => {
    try {
        await invoke('save_session');
    } catch (err) {
        console.error('[App] Failed to save session:', err);
    }
  };

  const handleLoadSession = async (name) => {
    try {
        const updated = await invoke('load_session', { name });
        if (!updated) return;
        setInstruments(updated.instruments);
        const entries = Object.entries(updated.instruments);
        if (entries.length > 0) {
            const [firstName, data] = entries[0];
            setSelectedInstrument({ name: firstName, ...data });
            setSwitchInstrument(k => k + 1);
        }
    } catch (err) {
        console.error('[App] Failed to load session:', err);
    }
  };


  // The instrument currently shown in the Setup tab.
  const [selectedInstrument, setSelectedInstrument] = useState(() => {
    const entries = Object.entries(instrumentsConfig.instruments);
    if (entries.length === 0) return null;
    const [name, data] = entries[0];
    return { name, ...data };
  });

  // Modal state
  const [modalOpen, setModalOpen] = useState(false);


  // handle instrument reconcile
  const handleReconcile = (updatedInstruments) => {
    setInstruments(updatedInstruments);
    setSelectedInstrument(prev => {
      const updated = updatedInstruments[prev?.name];
      return updated ? { name: prev.name, ...updated } : prev;
    });
  };

  // Called when the user clicks an instrument in the sidebar.
  const handleSelectInstrument = (name, data) => {
    setSelectedInstrument({ name, ...data });
    setSwitchInstrument(k => k + 1);
  };


  // Submit modal form handler
  const handleSubmit = async (formData) => {
    try {
      await invoke('save_instrument', { instrument: formData });

      const nonMixBefore = Object.keys(instruments).filter(k => k !== 'mix').length;
      if (nonMixBefore === 1 && !instruments.mix) {
        const mixToRestore = prevMixConfig.current ?? {
          name: 'mix',
          analysers: ['genre'],
          enabled: true,
          mix_source: 'internal',
          source_instruments: [],
          type: 'mix',
        };
        await invoke('save_instrument', { instrument: { name: 'mix', ...mixToRestore } });
      }

      const reconciled = await invoke('reconcile_devices');
      setInstruments(reconciled.instruments);
      setSelectedInstrument({ name: formData.name, ...reconciled.instruments[formData.name] });
      setSwitchInstrument(k => k + 1);
      setModalOpen(false);
    } catch (err) {
      console.error('[App] Failed to save instrument:', err);
    }
  };




  // Update instrument in setup tab
  const handleUpdateInstrument = async (originalName, formData) => {
    if (!formData.name) return; // don't persist an empty name

    const isRename = originalName !== formData.name;
    try {
      await invoke('save_instrument', { instrument: formData });
      if (isRename) await invoke('delete_instrument', { name: originalName });

      setInstruments(prev => {
        const next = { ...prev };
        if (isRename) delete next[originalName];
        next[formData.name] = { ...formData };
        return next;
      });

      // keep selectedInstrument in sync without triggering a switchKey bump
      // (a switchKey bump would reset Setup's local draft mid-edit)
      setSelectedInstrument({ ...formData });
    } catch (err) {
      console.error('[App] Failed to update instrument:', err);
    }
  };

  const handleDeleteInstrument = async (name) => {
    try {
      await invoke('delete_instrument', { name });

      const next = { ...instruments };
      delete next[name];

      // Count remaining non-mix instruments
      const nonMixRemaining = Object.keys(next).filter(k => k !== 'mix').length;

      if (nonMixRemaining <= 1 && next.mix) {
        // Drop to 1 or 0 non-mix instruments — remove mix from disk and state
        await invoke('delete_instrument', { name: 'mix' });
        delete next.mix;
      }

      setInstruments(next);

      // Select first remaining non-mix instrument, or null
      const remaining = Object.entries(next).filter(([k]) => k !== 'mix');
      if (remaining.length > 0) {
        const [nextName, nextData] = remaining[0];
        setSelectedInstrument({ name: nextName, ...nextData });
      } else {
        setSelectedInstrument(null);
      }
      setSwitchInstrument(k => k + 1);

    } catch (err) {
      console.error('[App] Failed to delete instrument:', err);
    }
  };


  // Swap instruments in setup tab
  const handleSwapDevices = async (nameA, newDeviceA, nameB, newDeviceB) => {
    try {
      const instrA = { name: nameA, ...instruments[nameA], audio_device: newDeviceA };
      const instrB = { name: nameB, ...instruments[nameB], audio_device: newDeviceB };
      await invoke('save_instrument', { instrument: instrA });
      await invoke('save_instrument', { instrument: instrB });

      setInstruments(prev => ({
        ...prev,
        [nameA]: { ...prev[nameA], audio_device: newDeviceA },
        [nameB]: { ...prev[nameB], audio_device: newDeviceB },
      }));

      // reflect the swap on whichever instrument is currently open in Setup
      setSelectedInstrument(prev => {
        if (prev?.name === nameA) return { ...prev, audio_device: newDeviceA };
        if (prev?.name === nameB) return { ...prev, audio_device: newDeviceB };
        return prev;
      });
    } catch (err) {
      console.error('[App] Failed to swap devices:', err);
    }
  };



  return (
     <>
      <Layout
        pipelineStatus={pipelineStatus}
        onStart={handleStart}
        onStop={handleStop}
        onAddInstrument={() => setModalOpen(true)}
        instruments={instruments}
        selectedInstrument={selectedInstrument}
        switchInstrument={switchInstrument}
        onSelectInstrument={handleSelectInstrument}
        onUpdateInstrument={handleUpdateInstrument}
        onSwapDevices={handleSwapDevices}
        onReconcile={handleReconcile}
        onDeleteInstrument={handleDeleteInstrument}
      />
      {modalOpen && (
        <AddInstrumentModal
          onClose={() => setModalOpen(false)}
          onSubmit={handleSubmit}
          instruments={instruments}
        />
      )}
    </>
  );
}

export default App;
