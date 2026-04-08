import React, { useEffect, useState } from 'react';
import { listen } from '@tauri-apps/api/event';
import styles from './OutputPanel.module.css';


const OutputPanel = () => {
    const [messages, setMessages] = useState([]);

    useEffect(()=> {

        // Listen for/Subscribe to OSC messages from the backend
        const unlisten = listen('osc-message', (event) => {
            const timestamp = new Date().toLocaleTimeString();
            setMessages(prev => [
                { id: Math.random(), text: event.payload, timestamp: timestamp },
                ...prev
            ]);
        });

        // cleanup lisner when component unmounts
        return () => {
            unlisten.then(fn => fn());
        }
    }, []);


    return (
    <div className={styles.outputPanel}>
        {messages.length === 0 ? (
            <p>Waiting for Output...</p>
        ) : (
            messages.map(msg => (
                <div key={msg.id} className={styles.message}>
                    <span className={styles.timestamp}>{msg.time}</span>
                    <span className={styles.text}>{msg.text}</span>
                </div>
            ))
        )}
    </div>
  );
};

export default OutputPanel;