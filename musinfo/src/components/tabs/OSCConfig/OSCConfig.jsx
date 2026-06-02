import React, { useState } from 'react';
import styles from './OSCConfig.module.css';

const IMAGE_GEN_PORT = 9001;
const TD_PORT        = 9100;

// ─── Address map ─────────────────────────────────────────────────────────────
// TD paths: /td/{analyser}/{role}/{role_index}/{param}
// Image gen paths: fixed addresses on port 9001
// Tempo pulse: global — no role/index segment
// MIDI harmony: fixed path /td/harmony/piano/midi/{param}

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
      { label: 'top mood',     path: '/prompt/mood',         type: 'string' },
      { label: 'danceability', path: '/prompt/danceability', type: 'float'  },
      { label: 'mood tags',    path: '/prompt/mood_tags',    type: 'string' },
    ],
  },
  tempo: {
    destination: 'both',
    image_gen_params: [
      { label: 'tempo feel', path: '/prompt/tempo_feel', type: 'string' },
    ],
    td_params: () => [
      { label: 'pulse', path: '/td/tempo/pulse', type: 'int'   },
      { label: 'bpm',   path: '/td/tempo/bpm',   type: 'float' },
    ],
  },
  timbre: {
    destination: 'touchdesigner',
    params: (role, role_index) => [
      { label: 'centroid',   path: `/td/timbre/${role}/${role_index}/centroid`,   type: 'float'     },
      { label: 'flux',       path: `/td/timbre/${role}/${role_index}/flux`,       type: 'float'     },
      { label: 'flatness',   path: `/td/timbre/${role}/${role_index}/flatness`,   type: 'float'     },
      { label: 'rolloff',    path: `/td/timbre/${role}/${role_index}/rolloff`,    type: 'float'     },
      { label: 'mfcc_delta', path: `/td/timbre/${role}/${role_index}/mfcc_delta`, type: 'float'    },
      { label: 'mfcc',       path: `/td/timbre/${role}/${role_index}/mfcc`,       type: 'float[13]' },
      { label: 'attack',     path: `/td/timbre/${role}/${role_index}/attack`,     type: 'float'     },
    ],
  },
  dynamics: {
    destination: 'touchdesigner',
    params: (role, role_index) => [
      { label: 'rms',            path: `/td/dynamics/${role}/${role_index}/rms`,           type: 'float' },
      { label: 'onset',          path: `/td/dynamics/${role}/${role_index}/onset`,          type: 'int'   },
      { label: 'onset strength', path: `/td/dynamics/${role}/${role_index}/onset_strength`, type: 'float' },
      { label: 'rms at onset',   path: `/td/dynamics/${role}/${role_index}/rms_at_onset`,  type: 'float' },
    ],
  },
  pitch: {
    destination: 'touchdesigner',
    params: (role, role_index) => [
      { label: 'hz', path: `/td/pitch/${role}/${role_index}/hz`, type: 'float' },
    ],
  },
  pitch_crepe: {
    destination: 'touchdesigner',
    params: (role, role_index) => [
      { label: 'hz', path: `/td/pitch/${role}/${role_index}/hz`, type: 'float' },
    ],
  },
  harmony: {
    destination: 'touchdesigner',
    params: (role, role_index) => [
      { label: 'chord',           path: `/td/harmony/${role}/${role_index}/chord`,           type: 'string'    },
      { label: 'chord quality',   path: `/td/harmony/${role}/${role_index}/chord_quality`,   type: 'string'    },
      { label: 'chord strength',  path: `/td/harmony/${role}/${role_index}/chord_strength`,  type: 'float'     },
      { label: 'roman degree',    path: `/td/harmony/${role}/${role_index}/roman_degree`,    type: 'string'    },
      { label: 'key',             path: `/td/harmony/${role}/${role_index}/key`,             type: 'string'    },
      { label: 'scale',           path: `/td/harmony/${role}/${role_index}/scale`,           type: 'string'    },
      { label: 'dissonance',      path: `/td/harmony/${role}/${role_index}/dissonance`,      type: 'float'     },
      { label: 'harmonic change', path: `/td/harmony/${role}/${role_index}/harmonic_change`, type: 'float'     },
      { label: 'hpcp',            path: `/td/harmony/${role}/${role_index}/hpcp`,            type: 'float[12]' },
    ],
  },
  // MIDI harmony always uses the fixed piano/midi path regardless of instrument name
  midi_harmony: {
    destination: 'touchdesigner',
    params: () => [
      { label: 'chord',           path: '/td/harmony/piano/midi/chord',           type: 'string'    },
      { label: 'chord quality',   path: '/td/harmony/piano/midi/chord_quality',   type: 'string'    },
      { label: 'chord strength',  path: '/td/harmony/piano/midi/chord_strength',  type: 'float'     },
      { label: 'roman degree',    path: '/td/harmony/piano/midi/roman_degree',    type: 'string'    },
      { label: 'key',             path: '/td/harmony/piano/midi/key',             type: 'string'    },
      { label: 'scale',           path: '/td/harmony/piano/midi/scale',           type: 'string'    },
      { label: 'dissonance',      path: '/td/harmony/piano/midi/dissonance',      type: 'float'     },
      { label: 'harmonic change', path: '/td/harmony/piano/midi/harmonic_change', type: 'float'     },
      { label: 'hpcp',            path: '/td/harmony/piano/midi/hpcp',            type: 'float[12]' },
    ],
  },
};

// ─── Derive rows from instruments prop ───────────────────────────────────────
function deriveAddresses(instruments) {
  const imageGenRows = [];
  const tdRows       = [];

  // Separate by type
  const audioInstruments = Object.entries(instruments)
    .filter(([, cfg]) => cfg.type === 'audio' || cfg.type === 'virtual');

  const midiInstruments = Object.entries(instruments)
    .filter(([, cfg]) => cfg.type === 'midi');

  const mixInstruments = Object.entries(instruments)
    .filter(([, cfg]) => cfg.type === 'mix');

  // Audio + virtual instruments
  audioInstruments.forEach(([name, cfg]) => {
    const role       = cfg.role       ?? 'default';
    const role_index = cfg.role_index ?? 0;

    const tdRows_inst  = [];
    const igRows_inst  = [];

    (cfg.analysers || []).forEach(analyser => {
      const def = ANALYSER_ADDRESSES[analyser];
      if (!def) return;

      if (def.destination === 'touchdesigner') {
        const params = typeof def.params === 'function'
          ? def.params(role, role_index)
          : def.params;
        params.forEach(p => tdRows_inst.push({ analyser, ...p }));

      } else if (def.destination === 'image_gen') {
        def.params.forEach(p => igRows_inst.push({ analyser, ...p }));

      } else if (def.destination === 'both') {
        def.image_gen_params.forEach(p => igRows_inst.push({ analyser, ...p }));
        def.td_params(role, role_index).forEach(p => tdRows_inst.push({ analyser, ...p }));
      }
    });

    if (tdRows_inst.length)  tdRows.push({ instrument: name, role, role_index, isMix: false, isMidi: false, rows: tdRows_inst });
    if (igRows_inst.length)  imageGenRows.push({ instrument: name, role, role_index, isMix: false, isMidi: false, rows: igRows_inst });
  });

  // MIDI instruments — harmony analyser only, fixed path
  midiInstruments.forEach(([name, cfg]) => {
    const tdRows_inst = [];
    (cfg.analysers || []).forEach(analyser => {
      // MIDI instruments use midi_harmony key for the fixed path
      const key = analyser === 'harmony' ? 'midi_harmony' : analyser;
      const def = ANALYSER_ADDRESSES[key];
      if (!def || def.destination === 'image_gen') return;
      const params = typeof def.params === 'function' ? def.params() : def.params;
      params.forEach(p => tdRows_inst.push({ analyser, ...p }));
    });
    if (tdRows_inst.length) tdRows.push({ instrument: name, isMix: false, isMidi: true, rows: tdRows_inst });
  });

  // Mix instruments
  mixInstruments.forEach(([name, cfg]) => {
    const role       = cfg.role       ?? 'mix';
    const role_index = cfg.role_index ?? 0;
    const igRows  = [];
    const tdExtra = [];

    (cfg.analysers || []).forEach(analyser => {
      const def = ANALYSER_ADDRESSES[analyser];
      if (!def) return;
      if (def.destination === 'image_gen')
        def.params.forEach(p => igRows.push({ analyser, ...p }));
      else if (def.destination === 'both') {
        def.image_gen_params.forEach(p => igRows.push({ analyser, ...p }));
        def.td_params().forEach(p => tdExtra.push({ analyser, ...p }));
      }
    });

    if (igRows.length)  imageGenRows.push({ instrument: name, role, role_index, isMix: true, isMidi: false, rows: igRows });
    if (tdExtra.length) tdRows.push({ instrument: name, role, role_index, isMix: true, isMidi: false, rows: tdExtra });
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
function InstrumentBlock({ instrument, role, role_index, isMix, isMidi, rows }) {
  return (
    <div className={styles.instrumentBlock}>
      <div className={styles.instrumentHeader}>
        <span className={styles.instrumentName}>{instrument}</span>
        {isMidi && <span className={styles.midiBadge}>midi</span>}
        {isMix  && <span className={styles.mixBadge}>mix</span>}
        {!isMidi && !isMix && role && (
          <span className={styles.roleBadge}>{role}/{role_index}</span>
        )}
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
      <Section title="TouchDesigner"    port={TD_PORT}        groups={tdRows}       />
      <Section title="Image generation" port={IMAGE_GEN_PORT} groups={imageGenRows} />
    </div>
  );
};

export default OSCConfig;