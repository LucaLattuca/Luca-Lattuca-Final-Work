import React from 'react';
import styles from './SignalPath.module.css';

const SignalPath = ({ name, audioDevice, analysers }) => {
  return (
    <>  
      <p className={styles.signalPathTitle}>Signal Path</p>
      <div className={styles.signalPath}>
        <p>{name}</p>          &rarr;
        <p>{audioDevice?.name}</p>     &rarr;
        <p>Musinfo</p> &rarr;
        <p>{analysers?.join(', ')}</p>    &rarr;
        <p>OSC output</p>
      </div>
    </>
  );
};

export default SignalPath;
