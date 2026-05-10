import React, { useState } from 'react';
import analysersConfig from '../../../../backend/config/analysers.json';
import styles from './AnalyserConfig.module.css';

// TODO refactor analysers -> analysers : clearer language

const AVAILABLE_ANALYSERS = Object.entries(analysersConfig.analysers).map(([id, data]) => ({
  id,
  ...data,
}));

const AnalyserConfig = ({ 
  selectedAnalysers, 
  onAnalysersChange,
  variant     = 'setup' //setup | modal
  }) => {
  const [hoveredAnalyser, setHoveredAnalyser] = useState(null);

  // toggle analysers
  const toggle = (id) => {
    onAnalysersChange(
      selectedAnalysers.includes(id)
        ? selectedAnalysers.filter(m => m !== id)
        : [...selectedAnalysers, id]
    );
  };

  return (
    <div className={`${styles.analyserSelection} ${styles[variant]}`}>
      <label>Select analysers</label>
      <div className={`${styles.analyserCards} ${styles[variant]}`}>
        {AVAILABLE_ANALYSERS.map((analyser) => {
          const isSelected = selectedAnalysers.includes(analyser.id);
          return (
            <button
              key={analyser.id}
              className={`${styles.analyserCard} ${isSelected ? styles.selectedCard : ''}`}
              onClick={() => toggle(analyser.id)}
              onMouseEnter={() => setHoveredAnalyser(analyser)}
              onMouseLeave={() => setHoveredAnalyser(null)}
            >
              <span className={styles.analyserName}>{analyser.id}</span>
            </button>
          );
        })}
      </div>
      <div className={styles.analyserDescription}>
        {hoveredAnalyser && <p>{hoveredAnalyser.explanation}</p>}
      </div>
    </div>
  );
};

export default AnalyserConfig;
