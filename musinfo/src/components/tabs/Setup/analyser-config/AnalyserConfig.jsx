import { useState } from 'react';
import React from 'react';
import styles from './AnalyserConfig.module.css';

const AnalyserConfig = () => {


  return (
    <div className={styles.analyserConfig}>
        <h2>Analyser Selection</h2>
        <ul className={styles.analyserList}>
          <li>
            <label>
              <input type="checkbox" name="genreAnalyser" />
              Genre Analyser
            </label>
          </li>
          <li>
            <label>
              <input type="checkbox" name="noteAnalyser" />
              Note Analyser
          </label>
        </li>
        </ul>
    </div>
  );
};

export default AnalyserConfig;
