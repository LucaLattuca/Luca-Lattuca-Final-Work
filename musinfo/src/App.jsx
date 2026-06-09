import reactLogo from "./assets/react.svg";
import { useState, useEffect, useRef  } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from '@tauri-apps/api/event';

import "./App.css";
import Layout from "./components/layout/Layout";
import AddInstrumentModal from "./components/modal/AddInstrumentModal";
import instrumentsConfig from "../backend/config/instruments.json";
import { resequenceRole } from "./utils/roleUtils";

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
    console.log('[handleSubmit] called with:', JSON.stringify({ name: formData.name, role: formData.role }));
    try {
      // Build next state including the new instrument, then resequence its entire role bucket.
      // This correctly assigns role_index to the new instrument AND updates any existing
      // instruments in the same role whose alphabetical position shifts.
      const next = { ...instruments, [formData.name]: { ...formData } };
      console.log('[handleSubmit] instruments before:', Object.keys(instruments));
      console.log('[handleSubmit] resequencing role:', formData.role);
      const bucketPatch = resequenceRole(next, formData.role);
      console.log('[handleSubmit] bucketPatch:', JSON.stringify(Object.fromEntries(Object.entries(bucketPatch).map(([k,v]) => [k, v.role_index]))));

      for (const [n, inst] of Object.entries(bucketPatch)) {
        console.log('[handleSubmit] saving:', n, 'role_index:', inst.role_index);
        const result = await invoke('save_instrument', { instrument: { name: n, ...inst } });
        console.log('[handleSubmit] save_instrument result for', n, ':', result);
      }

      const nonMixBefore = Object.keys(instruments).filter(k => k !== 'mix').length;
      console.log('[handleSubmit] nonMixBefore:', nonMixBefore, '| has mix:', !!instruments.mix);
      if (nonMixBefore === 1 && !instruments.mix) {
        const mixToRestore = prevMixConfig.current ?? {
          name: 'mix',
          analysers: ['genre'],
          enabled: true,
          mix_source: 'internal',
          source_instruments: [],
          type: 'mix',
        };
        console.log('[handleSubmit] restoring mix instrument');
        await invoke('save_instrument', { instrument: { name: 'mix', ...mixToRestore } });
      }

      console.log('[handleSubmit] calling reconcile_devices');
      const reconciled = await invoke('reconcile_devices');
      console.log('[handleSubmit] reconciled keys:', Object.keys(reconciled.instruments));
      setInstruments(reconciled.instruments);
      setSelectedInstrument({ name: formData.name, ...reconciled.instruments[formData.name] });
      setSwitchInstrument(k => k + 1);
      setModalOpen(false);
      console.log('[handleSubmit] complete');
    } catch (err) {
      console.error('[handleSubmit] ERROR:', err);
    }
  };




  // Update instrument in setup tab
  const handleUpdateInstrument = async (originalName, formData) => {
    if (!formData.name) return;

    const isRename    = originalName !== formData.name;
    const oldRole     = instruments[originalName]?.role;
    const newRole     = formData.role;
    const roleChanged = oldRole !== newRole;

    console.log('[handleUpdateInstrument] originalName:', originalName, '| newName:', formData.name);
    console.log('[handleUpdateInstrument] oldRole:', oldRole, '| newRole:', newRole, '| roleChanged:', roleChanged, '| isRename:', isRename);

    try {
      let next = { ...instruments };
      if (isRename) delete next[originalName];

      // If role changed, clear role_index so the instrument appends to end of new bucket.
      // If role is unchanged (name/analyser change), keep existing role_index for stable ordering.
      if (roleChanged) {
        next[formData.name] = { ...formData, role_index: null };
      } else {
        next[formData.name] = { ...formData };
      }

      // Always save the instrument itself first.
      // For regular instruments this is also covered by newBucketPatch below, but
      // mix has no role so resequenceRole returns {} and the loop never runs —
      // without this line, mix changes are silently dropped.
      await invoke('save_instrument', { instrument: { name: formData.name, ...next[formData.name] } });

      // Always resequence the new role bucket
      console.log('[handleUpdateInstrument] resequencing new bucket:', newRole);
      const newBucketPatch = resequenceRole(next, newRole);
      console.log('[handleUpdateInstrument] newBucketPatch:', JSON.stringify(Object.fromEntries(Object.entries(newBucketPatch).map(([k,v]) => [k, v.role_index]))));
      Object.assign(next, newBucketPatch);
      for (const [n, inst] of Object.entries(newBucketPatch)) {
        console.log('[handleUpdateInstrument] saving', n, 'role_index:', inst.role_index);
        await invoke('save_instrument', { instrument: { name: n, ...inst } });
      }

      // If role changed, also resequence the old bucket to fill the gap
      if (roleChanged && oldRole && oldRole !== 'mix') {
        console.log('[handleUpdateInstrument] resequencing old bucket:', oldRole);
        const oldBucketPatch = resequenceRole(next, oldRole);
        console.log('[handleUpdateInstrument] oldBucketPatch:', JSON.stringify(Object.fromEntries(Object.entries(oldBucketPatch).map(([k,v]) => [k, v.role_index]))));
        Object.assign(next, oldBucketPatch);
        for (const [n, inst] of Object.entries(oldBucketPatch)) {
          console.log('[handleUpdateInstrument] saving', n, 'role_index:', inst.role_index);
          await invoke('save_instrument', { instrument: { name: n, ...inst } });
        }
      }

      if (isRename) {
        console.log('[handleUpdateInstrument] deleting old key:', originalName);
        await invoke('delete_instrument', { name: originalName });
      }

      setInstruments(next);
      setSelectedInstrument({ name: formData.name, ...next[formData.name] });
      console.log('[handleUpdateInstrument] complete');
    } catch (err) {
      console.error('[handleUpdateInstrument] ERROR:', err);
    }
  };

  const handleDeleteInstrument = async (name) => {
    try {
      await invoke('delete_instrument', { name });

      const deletedRole = instruments[name]?.role;
      const next = { ...instruments };
      delete next[name];

      // Count remaining non-mix instruments
      const nonMixRemaining = Object.keys(next).filter(k => k !== 'mix').length;

      if (nonMixRemaining <= 1 && next.mix) {
        // Drop to 1 or 0 non-mix instruments — remove mix from disk and state
        await invoke('delete_instrument', { name: 'mix' });
        delete next.mix;
      }

      // Resequence the role bucket the deleted instrument belonged to
      // so the remaining instruments get contiguous 0-based indices
      if (deletedRole && deletedRole !== 'mix') {
        const patch = resequenceRole(next, deletedRole);
        Object.assign(next, patch);
        for (const [n, inst] of Object.entries(patch)) {
          await invoke('save_instrument', { instrument: { name: n, ...inst } });
        }
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