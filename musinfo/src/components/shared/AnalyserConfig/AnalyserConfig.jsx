import React, { useState } from 'react';
import modelsConfig from '../../../../backend/config/models.json';
import styles from './AnalyserConfig.module.css';

// TODO refactor models -> analysers : clearer language

const AVAILABLE_MODELS = Object.entries(modelsConfig.models).map(([id, data]) => ({
  id,
  ...data,
}));

const AnalyserConfig = ({ selectedModels, onModelsChange }) => {
  const [hoveredModel, setHoveredModel] = useState(null);

  // toggle analysers
  const toggle = (id) => {
    onModelsChange(
      selectedModels.includes(id)
        ? selectedModels.filter(m => m !== id)
        : [...selectedModels, id]
    );
  };

  return (
    <div className={styles.modelSelection}>
      <label>Select analysers</label>
      <div className={styles.modelCards}>
        {AVAILABLE_MODELS.map((model) => {
          const isSelected = selectedModels.includes(model.id);
          return (
            <button
              key={model.id}
              className={`${styles.modelCard} ${isSelected ? styles.selectedCard : ''}`}
              onClick={() => toggle(model.id)}
              onMouseEnter={() => setHoveredModel(model)}
              onMouseLeave={() => setHoveredModel(null)}
            >
              <span className={styles.modelName}>{model.id}</span>
            </button>
          );
        })}
      </div>
      <div className={styles.modelDescription}>
        {hoveredModel && <p>{hoveredModel.explenation}</p>}
      </div>
    </div>
  );
};

export default AnalyserConfig;
