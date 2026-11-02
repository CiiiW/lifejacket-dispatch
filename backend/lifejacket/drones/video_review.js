/* Provisional reviews only. No backend requests, dispatch, model calls or accuracy scores. */
'use strict';
(() => {
  const data = JSON.parse(document.getElementById('review-data').textContent);
  const reviewer = document.getElementById('reviewer');
  const status = document.getElementById('review-status');
  const cards = Array.from(document.querySelectorAll('article[data-frame]'));
  const key = `lifejacket-video-review-v1:${data.manifest_sha256}:${data.predictions_sha256}`;
  const field = (card, name) => card.querySelector(`[data-field="${name}"]`);
  const text = value => String(value ?? '');

  function snapshot() {
    return {schema_version: 1, manifest_sha256: data.manifest_sha256,
      predictions_sha256: data.predictions_sha256, reviewer: reviewer.value,
      frames: cards.map(card => ({scene: field(card, 'scene').value,
        presence: field(card, 'presence').value, missed: field(card, 'missed').value,
        note: field(card, 'note').value,
        regions: Array.from(card.querySelectorAll('[data-region]')).map(input => input.value)}))};
  }
  function assignSelect(input, value) {
    if (Array.from(input.options).some(option => option.value === value)) input.value = value;
  }
  try {
    const savedText = localStorage.getItem(key);
    if (savedText) {
      const saved = JSON.parse(savedText);
      if (saved.schema_version !== 1 || saved.manifest_sha256 !== data.manifest_sha256 ||
          saved.predictions_sha256 !== data.predictions_sha256 ||
          !Array.isArray(saved.frames) || saved.frames.length !== cards.length) {
        throw new Error('Review snapshot mismatch');
      }
      reviewer.value = text(saved.reviewer).slice(0, 80);
      cards.forEach((card, index) => {
        const row = saved.frames[index];
        assignSelect(field(card, 'scene'), row.scene);
        assignSelect(field(card, 'presence'), row.presence);
        field(card, 'missed').value = /^[0-9]+$/.test(text(row.missed)) &&
          Number(row.missed) <= 10000 ? row.missed : '';
        field(card, 'note').value = text(row.note).slice(0, 2000);
        card.querySelectorAll('[data-region]').forEach((input, i) =>
          assignSelect(input, row.regions?.[i]));
      });
      status.textContent = 'Restored edits from this browser. Export JSON for a portable copy.';
    } else status.textContent = 'No reviews yet. Model boxes remain unverified.';
  } catch {
    status.textContent = 'Browser storage unavailable or unreadable. Export JSON before leaving.';
  }
  function save() {
    document.getElementById('export-json').value = '';
    try {
      localStorage.setItem(key, JSON.stringify(snapshot()));
      status.textContent = 'Edits saved in this browser only. Export JSON for a portable copy.';
    } catch {
      status.textContent = 'Edits are not saved. Browser storage unavailable; export JSON now.';
    }
  }
  document.addEventListener('input', event => {
    if (event.target.matches('#reviewer, [data-field], [data-region]')) save();
  });
  document.addEventListener('change', event => {
    if (event.target.matches('[data-field], [data-region]')) save();
  });
  function exportReview() {
    if (!reviewer.value.trim()) {
      status.textContent = 'Enter a reviewer name before exporting.';
      reviewer.focus(); return;
    }
    const values = snapshot();
    const output = {...data, exported_at: new Date().toISOString(),
      reviewer: reviewer.value.trim(), model_visible: true, independent_ground_truth: false,
      review_kind: 'provisional_visual_review',
      frames: data.frames.map((frame, index) => {
        const row = values.frames[index];
        const missedInput = field(cards[index], 'missed');
        if (missedInput.validity.badInput ||
            (row.missed !== '' && (!/^[0-9]+$/.test(row.missed) || Number(row.missed) > 10000))) {
          throw new Error(`Frame ${index + 1}: missed count must be a whole number from 0 to 10000 or blank.`);
        }
        const touched = row.scene !== 'unreviewed' || row.presence !== 'unreviewed' ||
          row.missed !== '' || row.note.trim() || row.regions.some(v => v !== 'unreviewed');
        const complete = row.scene !== 'unreviewed' && row.presence !== 'unreviewed' &&
          row.note.trim() && row.regions.every(v => v !== 'unreviewed');
        return {...frame, review: {state: !touched ? 'unreviewed' : complete ? 'reviewed' : 'draft',
          scene: row.scene, visible_animals: row.presence,
          missed_visible_animals: row.missed === '' ? null : Number(row.missed),
          note: row.note.trim(), candidate_judgements: row.regions}};
      })};
    const json = JSON.stringify(output, null, 2);
    document.getElementById('export-json').value = json;
    document.querySelector('details').open = true;
    const url = URL.createObjectURL(new Blob([json], {type: 'application/json'}));
    const link = document.createElement('a');
    link.href = url;
    link.download = `provisional-review-${data.manifest_sha256.slice(0, 12)}-${Date.now()}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    status.textContent = 'JSON export prepared and download requested. Keep the downloaded file; no server copy was saved.';
  }
  document.getElementById('export').addEventListener('click', () => {
    try { exportReview(); }
    catch (error) { status.textContent = error.message || 'Could not export the review.'; }
  });
})();
