import React from 'react';
import Header from './Header';
import Sidebar from './Sidebar';
import Tabcontent from './Tabcontent';
import OutputPanel from './OutputPanel';
import style from './Layout.module.css';

const Layout = ({ 
    onAddInstrument,
    instruments,
    selectedInstrument,
    switchInstrument,
    onSelectInstrument,
    onUpdateInstrument,
    onSwapDevices,
    onReconcile,
    onDeleteInstrument,
    pipelineStatus,
    onStart,
    onStop,
}) => {
    const [activeTab, setActiveTab] = React.useState('setup');

    return (
        <>
          <Header 
            activeTab={activeTab} 
            setActiveTab={setActiveTab} 
            pipelineStatus={pipelineStatus}
            onStart={onStart}
            onStop={onStop}
          />
          <main className={style.main}>
            <Sidebar
              onAddInstrument={onAddInstrument}
              onSelectInstrument={onSelectInstrument}
              selectedInstrument={selectedInstrument}
              instruments={instruments}
            />
            <Tabcontent
              activeTab={activeTab}
              selectedInstrument={selectedInstrument}
              switchInstrument={switchInstrument}
              instruments={instruments}
              onUpdateInstrument={onUpdateInstrument}
              onSwapDevices={onSwapDevices}
              onReconcile={onReconcile}
              onDeleteInstrument={onDeleteInstrument}
              pipelineStatus={pipelineStatus}
            />
            <OutputPanel
              instruments={instruments}
            />
          </main>
        </>
    );
};

export default Layout