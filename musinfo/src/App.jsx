import { useState } from "react";
import reactLogo from "./assets/react.svg";
import { invoke } from "@tauri-apps/api/core";
import "./App.css";
import AudioDevices from "./components/terminal/AudioDevices";

function App() {
 
  return (
    <>  
      <AudioDevices />
    </>
  );
}

export default App;
