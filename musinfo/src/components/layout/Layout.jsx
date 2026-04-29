import React from 'react';
import Header from './Header';
import Sidebar from './Sidebar';
import Tabcontent from './Tabcontent';
import style from './Layout.module.css';
import OutputPanel from './OutputPanel';


const Layout = ({ onAddInstrument }) => {
    const [activeTab, setActiveTab] = React.useState('performance');
    const [selectedInstrument, setSelectedInstrument] = React.useState(null);


    const handleSelectInstrument = (name, data) => {
        const instrument = { name, ...data };
        setSelectedInstrument(instrument);
        console.log('[Layout] Selected instrument:', instrument);
    };

    return (
        <>
            <Header activeTab={activeTab} setActiveTab={setActiveTab} />
            <main className={style.main}>
                <Sidebar 
                    onAddInstrument={onAddInstrument}
                    onSelectInstrument={handleSelectInstrument}
                    selectedInstrument={selectedInstrument}
                />
                <Tabcontent  activeTab={activeTab} selectedInstrument={selectedInstrument}/>
                <OutputPanel />
            </main>
        </>
    );
};

export default Layout;
