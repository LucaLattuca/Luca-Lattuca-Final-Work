import React from 'react';

const SCRIABIN_COLORS = {
  'C':     '#ff0000',
  'G':     '#ff8c00',
  'D':     '#ffff00',
  'A':     '#148b14',
  'E':     '#669dfb',
  'B':     '#3535ff',
  'F#/Gb': '#00bfff',
  'Db':    '#8000af',
  'Ab':    '#a675c7',
  'Eb':    '#a44a93',
  'Bb':    '#a8748e',
  'F':     '#8b0027',
};

const WHITE_KEYS = ['C', 'D', 'E', 'F', 'G', 'A', 'B'];
const BLACK_KEYS = [
  { note: 'Db',    position: 0 },
  { note: 'Eb',    position: 1 },
  { note: 'F#/Gb', position: 3 },
  { note: 'Ab',    position: 4 },
  { note: 'Bb',    position: 5 },
];

const KEY_W = 52;
const KEY_H = 180;
const BK_W  = 32;
const BK_H  = 120;
const GAP   = 2;

const totalWidth = WHITE_KEYS.length * (KEY_W + GAP) - GAP;

const PianoKeyboard = ({ selectedKey, onKeySelect }) => (
  <svg
    width={totalWidth}
    height={KEY_H}
    style={{ display: 'block', cursor: 'pointer', userSelect: 'none' }}
  >
    {WHITE_KEYS.map((note, i) => {
      const x = i * (KEY_W + GAP);
      const isSelected = selectedKey === note;
      return (
        <g key={note} onClick={() => onKeySelect(note)}>
          <rect
            x={x} y={0}
            width={KEY_W} height={KEY_H}
            rx={4}
            fill={isSelected ? SCRIABIN_COLORS[note] : '#e8e8e8'}
            stroke={isSelected ? SCRIABIN_COLORS[note] : '#999'}
            strokeWidth={1}
            style={{ transition: 'fill 0.15s' }}
          />
          <text
            x={x + KEY_W / 2} y={KEY_H - 14}
            textAnchor="middle" fontSize={11}
            fill={isSelected ? '#fff' : '#555'}
            style={{ pointerEvents: 'none' }}
          >
            {note}
          </text>
        </g>
      );
    })}

    {BLACK_KEYS.map(({ note, position }) => {
      const x = position * (KEY_W + GAP) + KEY_W - BK_W / 2;
      const isSelected = selectedKey === note;
      return (
        <g key={note} onClick={() => onKeySelect(note)}>
          <rect
            x={x} y={0}
            width={BK_W} height={BK_H}
            rx={3}
            fill={isSelected ? SCRIABIN_COLORS[note] : '#1a1a1a'}
            stroke={isSelected ? SCRIABIN_COLORS[note] : '#000'}
            strokeWidth={1}
            style={{ transition: 'fill 0.15s' }}
          />
          <text
            x={x + BK_W / 2} y={BK_H - 10}
            textAnchor="middle" fontSize={9}
            fill={isSelected ? '#fff' : '#aaa'}
            style={{ pointerEvents: 'none' }}
          >
            {note}
          </text>
        </g>
      );
    })}
  </svg>
);

export default PianoKeyboard;