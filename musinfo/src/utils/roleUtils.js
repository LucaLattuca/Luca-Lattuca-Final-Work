// roleUtils.js — role_index helpers shared by App, Modal, and Setup
// role_index is stored in instruments.json as the single source of truth.

/**
 * Given the full instruments map, return a map of { instrumentName -> role_index }.
 */
export function computeRoleIndices(instruments) {
  const buckets = {};
  Object.entries(instruments).forEach(([name, inst]) => {
    if (inst.type === 'mix') return;
    const role = inst.role || 'default';
    if (!buckets[role]) buckets[role] = [];
    buckets[role].push(name);
  });

  const indices = {};
  Object.entries(buckets).forEach(([, names]) => {
    names.sort().forEach((name, i) => {
      indices[name] = i;
    });
  });
  return indices;
}

/**
 * Returns a patch object { [name]: { ...inst, role_index: N } } for every instrument
 * in the given role bucket, resequenced 0-based.
 *
 * Sort order:
 *   1. Instruments with a defined role_index keep their relative order (stable, insertion-order)
 *   2. Instruments with null/undefined role_index are appended at the end
 *   3. Alphabetical tiebreaker for instruments in the same position
 *
 * This means: existing instruments keep their slots, newly added or newly assigned
 * instruments are appended — which matches user expectation.
 */
export function resequenceRole(instruments, role) {
  if (!role || role === 'mix') {
    console.warn('[resequenceRole] called with empty or mix role:', role, '— returning {}');
    return {};
  }

  const members = Object.entries(instruments)
    .filter(([, inst]) => inst.role === role && inst.type !== 'mix')
    .map(([name, inst]) => ({ name, idx: inst.role_index ?? null }))
    .sort((a, b) => {
      const aNull = a.idx === null || a.idx === undefined;
      const bNull = b.idx === null || b.idx === undefined;
      if (!aNull && !bNull) return a.idx - b.idx;  // both defined: numeric order
      if (!aNull) return -1;                         // a defined, b null: a first
      if (!bNull) return 1;                          // b defined, a null: b first
      return a.name.localeCompare(b.name);           // both null: alphabetical
    })
    .map(({ name }) => name);

  console.log('[resequenceRole] role:', role, '| members (insertion order):', members);

  const patch = {};
  members.forEach((name, i) => {
    patch[name] = { ...instruments[name], role_index: i };
  });

  console.log('[resequenceRole] result:', JSON.stringify(Object.fromEntries(Object.entries(patch).map(([k, v]) => [k, v.role_index]))));
  return patch;
}