import React, {useState} from 'react';
import styles from './InstrumentConfig.module.css';

const INPUT_TYPES = [
  {
    id: "midi",
    label: "MIDI",
    description: "Keyboard, pad controllers, or any MIDI devices",
    icon: "♪",
  },
  {
    id: "audio",
    label: "Audio",
    description: "Microphone, guitar, line-in via audio interface...",
    icon: "♫",
  },
  {
    id: "virtual",
    label: "Virtual",
    description: "Software instruments or DAW outputs",
    icon: "🌐",
  },
]

const InstrumentConfig = ({
  name        = '',
  onNameChange,
  type        = '',
  onTypeChange,
  showName    = true,
  showType    = true,
  variant     = 'setup' //setup | modal
}) => {

  const selectedInputType = INPUT_TYPES.find(t => t.id === type);

  const [hoveredType, setHoveredType] = useState(null);

  const displayedType = hoveredType ?? selectedInputType;


  return (
    <div className={`${styles[variant]}`}>
      {showName && (
        <div className={styles.instrumentNameInput}>
          <label>Instrument name</label>
          <input
            type="text"
            placeholder="vocals, guitar, piano, synthesizer"
            maxLength={24}
            value={name}
            onChange={e => {
              const cleaned = e.target.value
                .toLowerCase()
                .replace(/\s+/g, '_')
                .replace(/[^a-z0-9_]/g, '');
              onNameChange(cleaned);
            }}
          />
        </div>
      )}
      
      
       {showType && (
        <div className={styles.InputCards}>
          {INPUT_TYPES.map(({ id, label, description, icon }) => (
            <button
              key={id}
              className={`${styles.card} ${type === id ? styles.selectedCard : ''}`}
              onClick={() => onTypeChange(id)}
              onMouseEnter={() => variant === 'setup' && setHoveredType({ id, description })}
              onMouseLeave={() => variant === 'setup' && setHoveredType(null)}
            >
              {/* only show icon and description when on modal*/}
              {variant === 'modal' && <p className={styles.cardIcon}>{icon}</p>}
              <h2 className={styles.cardLabel}>{label}</h2>
              {variant === 'modal' && <p className={styles.cardDesc}>{description}</p>}
            </button>
          ))}
        </div>
      )}

      {/* show description outside of element within setup tab */}
      {showType && variant === 'setup' && (
        <p className={styles.typeDescription}>
          {displayedType ? displayedType.description : '\u00A0'}
        </p>
      )}

    </div>
  );
};

export default InstrumentConfig;