import reactLogo from "./assets/react.svg";
import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";

import "./App.css";
import Layout from "./components/layout/Layout";
import AddInstrumentModal from "./components/modal/AddInstrumentModal";
import instrumentsConfig from "../backend/config/instruments.json";

function App() {

  const [modalOpen, setModalOpen] = useState(false);

  const [instruments, setInstruments] = useState(instrumentsConfig.instruments);

  // Submit modal form handler
  const handleSubmit = async (formData) => {
    try {
      await invoke('save_instrument', { instrument: formData });
      console.log('[App] Instrument saved:', formData.name);
      setInstruments(prev => ({
                ...prev,
                [formData.name]: formData,
            }));
      setModalOpen(false);
    } catch (err) {
      console.error('[App] Failed to save instrument:', err);
    }
  };

  return (
    <>  
      <Layout 
        onAddInstrument={() => setModalOpen(true)} 
        instruments={instruments}  
      />
      {modalOpen && (
        <AddInstrumentModal
          onClose={() => setModalOpen(false)}
          onSubmit={handleSubmit}
        />
      )}
    </>
  );
}

export default App;
