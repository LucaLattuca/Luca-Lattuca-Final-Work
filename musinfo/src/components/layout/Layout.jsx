import React from 'react';
import Header from './Header';
import Sidebar from './Sidebar';
import Tabcontent from './Tabcontent';
import style from './Layout.module.css';
import OutputPanel from './OutputPanel';


const Layout = ({ onAddInstrument }) => {
    const [activeTab, setActiveTab] = React.useState('performance');
    return (
        <>
            <Header activeTab={activeTab} setActiveTab={setActiveTab} />
            <main className={style.main}>
                <Sidebar onAddInstrument={onAddInstrument}/>
                <Tabcontent  activeTab={activeTab}/>
                <OutputPanel />
            </main>
        </>
    );
};

export default Layout;
