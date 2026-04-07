import { useState } from "react";
import reactLogo from "./assets/react.svg";
import { invoke } from "@tauri-apps/api/core";
import "./App.css";
import Layout from "./components/layout/Layout";

function App() {
 
  return (
    <>  
      <Layout />
    </>
  );
}

export default App;
