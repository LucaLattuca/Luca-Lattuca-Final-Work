import React from 'react';
import Header from './Header';
import Sidebar from './Sidebar';
import Tabcontent from './Tabcontent';
import style from './Layout.module.css';

const Layout = () => {
    return (
        <>
            <Header />
            <main className={style.main}>
                <Sidebar/>
                <Tabcontent />
            </main>
        </>
    );
};

export default Layout;
