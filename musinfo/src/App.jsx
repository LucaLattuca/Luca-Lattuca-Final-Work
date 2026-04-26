import { useState } from "react";
import reactLogo from "./assets/react.svg";
import { invoke } from "@tauri-apps/api/core";

import "./App.css";
import Layout from "./components/layout/Layout";
import Modal from "./components/modal/AddInstrumentModal"
import AddInstrumentModal from "./components/modal/AddInstrumentModal";
function App() {

  // Add instrument modal state
  const [modalOpen, setModalOpen] = useState(false);

  // Submit modal form handler
  const handleSubmit = async (formData) => {
    try {
      await invoke('save_instrument', { instrument: formData });
      console.log('[App] Instrument saved:', formData.name);
      setModalOpen(false);
    } catch (err) {
      console.error('[App] Failed to save instrument:', err);
    }
  };

  return (
    <>  
      <Layout onAddInstrument={() => setModalOpen(true)} />
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
