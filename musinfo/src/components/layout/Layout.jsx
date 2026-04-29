import React from 'react';
import Header from './Header';
import Sidebar from './Sidebar';
import Tabcontent from './Tabcontent';
import style from './Layout.module.css';
import OutputPanel from './OutputPanel';


const Layout = ({ onAddInstrument, instruments }) => {
    const [activeTab, setActiveTab] = React.useState('performance');
    
    const [selectedInstrument, setSelectedInstrument] = React.useState(() => {
        const entries = Object.entries(instruments);
        if (entries.length === 0) return null;
        const [name, data] = entries[0];
        return { name, ...data };
    });

    // when instrument updates, select new instrument
    React.useEffect(() => {
        const entries = Object.entries(instruments);
        if (entries.length === 0) { setSelectedInstrument(null); return; }

        const stillExists = selectedInstrument && instruments[selectedInstrument.name];
        if (!stillExists) {
            const [name, data] = entries[0];
            setSelectedInstrument({ name, ...data });
        }
    }, [instruments]);


    const handleSelectInstrument = (name, data) => {
        setSelectedInstrument({ name, ...data });
        console.log('[Layout] Selected instrument:', { name, ...data });
    };

    return (
        <>
            <Header activeTab={activeTab} setActiveTab={setActiveTab} />
            <main className={style.main}>
                <Sidebar 
                    onAddInstrument={onAddInstrument}
                    onSelectInstrument={handleSelectInstrument}
                    selectedInstrument={selectedInstrument}
                    instruments={instruments}
                />
                <Tabcontent  activeTab={activeTab} selectedInstrument={selectedInstrument}/>
                <OutputPanel />
            </main>
        </>
    );
};

export default Layout;
