import { useState } from "react";
import reactLogo from "./assets/react.svg";
import { invoke } from "@tauri-apps/api/core";
import "./App.css";
import Layout from "./components/layout/Layout";
import Modal from "./components/modal/AddInstrumentModal"
import AddInstrumentModal from "./components/modal/AddInstrumentModal";
function App() {
 
  return (
    <>  
      <Layout />
      <AddInstrumentModal/>
    </>
  );
}

export default App;
