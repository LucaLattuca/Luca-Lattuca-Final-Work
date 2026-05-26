import React, { useState } from 'react';
import styles from './OSCConfig.module.css';

const IMAGE_GEN_PORT = 9001;
const TD_PORT        = 9100;

// ─── Address map ─────────────────────────────────────────────────────────────
const ANALYSER_ADDRESSES = {
  genre: {
    destination: 'image_gen',
    params: [
      { label: 'top genres', path: '/prompt/genre', type: 'JSON' },
    ],
  },
  mood: {
    destination: 'image_gen',
    params: [
      { label: 'top mood',     path: '/prompt/mood',          type: 'string' },
      { label: 'danceability', path: '/prompt/danceability',  type: 'float'  },
      { label: 'mood tags',    path: '/prompt/mood_tags',     type: 'string' },
    ],
  },
  // tempo splits: bpm/feel → image gen (tempo_cnn, port 9001)
  //               pulse    → TD       (tempo_analyser, port 9100)
  tempo: {
    destination: 'both',
    image_gen_params: [
      { label: 'feel', path: '/prompt/tempo_feel',  type: 'string' },
    ],
    td_params: (name, idx) => [
      { label: 'pulse', path: `/td/tempo/pulse`, type: 'int' },
    ],
  },
  // TD analysers: /td/{analyser}/{index}/{param}
  // index = position among type:audio instruments sorted alphabetically
  timbre: {
    destination: 'touchdesigner',
    params: (name, idx) => [
      { label: 'centroid',   path: `/td/timbre/${idx}/centroid`,   type: 'float'     },
      { label: 'flux',       path: `/td/timbre/${idx}/flux`,       type: 'float'     },
      { label: 'flatness',   path: `/td/timbre/${idx}/flatness`,   type: 'float'     },
      { label: 'rolloff',    path: `/td/timbre/${idx}/rolloff`,    type: 'float'     },
      { label: 'mfcc_delta', path: `/td/timbre/${idx}/mfcc_delta`, type: 'float'     },
      { label: 'mfcc',       path: `/td/timbre/${idx}/mfcc`,       type: 'float[13]' },
      { label: 'attack',     path: `/td/timbre/${idx}/attack`,     type: 'float'     },
    ],
  },
  dynamics: {
    destination: 'touchdesigner',
    params: (name, idx) => [
      { label: 'rms',            path: `/td/dynamics/${idx}/rms`,            type: 'float' },
      { label: 'onset',          path: `/td/dynamics/${idx}/onset`,           type: 'int'   },
      { label: 'onset strength', path: `/td/dynamics/${idx}/onset_strength`,  type: 'float' },
      { label: 'rms at onset',   path: `/td/dynamics/${idx}/rms_at_onset`,    type: 'float' },
    ],
  },
  pitch: {
    destination: 'touchdesigner',
    params: (name, idx) => [
      { label: 'note + hz', path: `/td/pitch/${idx}/note`, type: 'string' },
    ],
  },
  harmony: {
    destination: 'touchdesigner',
    params: (name, idx) => [
      { label: 'chord',          path: `/td/harmony/${idx}/chord`,           type: 'string'    },
      { label: 'chord quality',  path: `/td/harmony/${idx}/chord_quality`,   type: 'string'    },
      { label: 'chord strength', path: `/td/harmony/${idx}/chord_strength`,  type: 'float'     },
      { label: 'roman degree',   path: `/td/harmony/${idx}/roman_degree`,    type: 'string'    },
      { label: 'key',            path: `/td/harmony/${idx}/key`,             type: 'string'    },
      { label: 'scale',          path: `/td/harmony/${idx}/scale`,           type: 'string'    },
      { label: 'dissonance',     path: `/td/harmony/${idx}/dissonance`,      type: 'float'     },
      { label: 'harmonic change',path: `/td/harmony/${idx}/harmonic_change`, type: 'float'     },
      { label: 'hpcp',           path: `/td/harmony/${idx}/hpcp`,            type: 'float[12]' },
    ],
  },
};

// ─── Derive rows from instruments prop ───────────────────────────────────────
function deriveAddresses(instruments) {
  const imageGenRows = [];
  const tdRows       = [];

  const audioInstruments = Object.entries(instruments)
    .filter(([, cfg]) => cfg.type === 'audio' || cfg.type === 'virtual')
    .sort(([a], [b]) => a.localeCompare(b));

  const mixInstruments = Object.entries(instruments)
    .filter(([, cfg]) => cfg.type === 'mix');

  // Audio + virtual instruments → route each analyser by its own destination
  audioInstruments.forEach(([name, cfg], idx) => {
    const tdRows_inst = [];
    (cfg.analysers || []).forEach(analyser => {
      const def = ANALYSER_ADDRESSES[analyser];
      if (!def) return;
      if (def.destination === 'touchdesigner') {
        (typeof def.params === 'function' ? def.params(name, idx) : def.params)
          .forEach(p => tdRows_inst.push({ analyser, ...p }));
      } else if (def.destination === 'image_gen') {
        // collect into a per-instrument image gen group
        def.params.forEach(p => {
          // find or create the image gen group for this instrument
          let group = imageGenRows.find(g => g.instrument === name);
          if (!group) { group = { instrument: name, isMix: false, rows: [] }; imageGenRows.push(group); }
          group.rows.push({ analyser, ...p });
        });
      } else if (def.destination === 'both') {
        def.image_gen_params.forEach(p => {
          let group = imageGenRows.find(g => g.instrument === name);
          if (!group) { group = { instrument: name, isMix: false, rows: [] }; imageGenRows.push(group); }
          group.rows.push({ analyser, ...p });
        });
        def.td_params(name).forEach(p => tdRows_inst.push({ analyser, ...p }));
      }
    });
    if (tdRows_inst.length) tdRows.push({ instrument: name, index: idx, isMix: false, rows: tdRows_inst });
  });

  // Mix instruments — same logic, always last
  mixInstruments.forEach(([name, cfg]) => {
    const igRows  = [];
    const tdExtra = [];
    (cfg.analysers || []).forEach(analyser => {
      const def = ANALYSER_ADDRESSES[analyser];
      if (!def) return;
      if (def.destination === 'image_gen')
        def.params.forEach(p => igRows.push({ analyser, ...p }));
      else if (def.destination === 'both') {
        def.image_gen_params.forEach(p => igRows.push({ analyser, ...p }));
        def.td_params(name).forEach(p => tdExtra.push({ analyser, ...p }));
      }
    });
    if (igRows.length)  imageGenRows.push({ instrument: name, isMix: true, rows: igRows });
    if (tdExtra.length) tdRows.push({ instrument: name, isMix: true, rows: tdExtra });
  });

  return { imageGenRows, tdRows };
}
// ─── Copy button ──────────────────────────────────────────────────────────────
function CopyIcon({ text }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    });
  };
  return (
    <button onClick={copy} className={styles.copyBtn} title="Copy address">
      {copied
        ? <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#4ade80" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
        : <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#6b7280" strokeWidth="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
      }
    </button>
  );
}

// ─── Type badge ───────────────────────────────────────────────────────────────
function TypeBadge({ type }) {
  const cls = type.startsWith('float[')
    ? styles['type-array']
    : (styles[`type-${type}`] || styles['type-float']);
  return <span className={`${styles.typeBadge} ${cls}`}>{type}</span>;
}

// ─── Address table ────────────────────────────────────────────────────────────
function AddressTable({ rows }) {
  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th className={styles.thAnalyser}>analyser</th>
          <th className={styles.thLabel}>parameter</th>
          <th className={styles.thPath}>osc address</th>
          <th className={styles.thType}>type</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => {
          const showLabel = i === 0 || rows[i - 1].analyser !== row.analyser;
          return (
            <tr key={i} className={showLabel && i !== 0 ? styles.groupGap : ''}>
              <td className={styles.tdAnalyser}>
                {showLabel && (
                  <span className={`${styles.analyserLabel} ${styles[`analyser-${row.analyser}`]}`}>
                    {row.analyser}
                  </span>
                )}
              </td>
              <td className={styles.tdLabel}>{row.label}</td>
              <td className={styles.tdPath}>
                <CopyIcon text={row.path} />
                <code className={styles.oscCode}>{row.path}</code>
              </td>
              <td className={styles.tdType}>
                <TypeBadge type={row.type} />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// ─── Instrument block ─────────────────────────────────────────────────────────
function InstrumentBlock({ instrument, index, isMix, rows }) {
  return (
    <div className={styles.instrumentBlock}>
      <div className={styles.instrumentHeader}>
        <span className={styles.instrumentName}>{instrument}</span>
        {!isMix && index !== undefined && <span className={styles.indexBadge}>#{index}</span>}
        {isMix && <span className={styles.mixBadge}>mix</span>}
      </div>
      <AddressTable rows={rows} />
      <div className={styles.instrumentDivider} />
    </div>
  );
}

// ─── Section ──────────────────────────────────────────────────────────────────
function Section({ title, port, groups }) {
  return (
    <div className={styles.section}>
      <div className={styles.sectionHeader}>
        <span className={styles.sectionTitle}>{title}</span>
        <span className={styles.portBadge}>:{port}</span>
      </div>
      {groups.length === 0
        ? <p className={styles.empty}>No analysers configured for this destination.</p>
        : groups.map(g => <InstrumentBlock key={g.instrument} {...g} />)
      }
    </div>
  );
}

// ─── Root ─────────────────────────────────────────────────────────────────────
const OSCConfig = ({ instruments = {} }) => {
  const { imageGenRows, tdRows } = deriveAddresses(instruments);
  return (
    <div className={styles.container}>
      <Section title="TouchDesigner"    port={TD_PORT}        groups={tdRows} />
      <Section title="Image generation" port={IMAGE_GEN_PORT} groups={imageGenRows} />
    </div>
  );
};

export default OSCConfig;