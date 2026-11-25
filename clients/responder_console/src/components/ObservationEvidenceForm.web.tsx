import { useEffect, useState } from 'react';

import type { DroneRequest } from '../lib/networkApi';
import RecordedFramePicker, { type RecordedFrame } from './RecordedFramePicker.web';

export default function ObservationEvidenceForm({
  request, busy, onUpload,
}: {
  request: DroneRequest;
  busy: boolean;
  onUpload: (data: FormData) => void;
}) {
  const [frame, setFrame] = useState<RecordedFrame | null>(null);
  const [preview, setPreview] = useState('');
  const [image, setImage] = useState<File | null>(null);
  const [source, setSource] = useState('');
  const [rights, setRights] = useState('');
  const [description, setDescription] = useState('');
  const [captureTime, setCaptureTime] = useState('');
  const [offset, setOffset] = useState('');
  const recorded = request.execution_kind === 'recorded_demo';

  useEffect(() => {
    if (!frame) {
      setPreview('');
      return;
    }
    const url = URL.createObjectURL(frame.image);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [frame]);

  return <form aria-label="Attach drone evidence" onSubmit={event => {
    event.preventDefault();
    const photo = frame?.image ?? image;
    if (!photo || busy) return;
    const data = new FormData();
    data.set('metadata', JSON.stringify({
      revision: request.revision,
      source_kind: recorded ? 'sample_footage' : 'operator_capture',
      source_url: source || null,
      rights_note: rights,
      description,
      captured_at: captureTime ? new Date(captureTime).toISOString() : null,
      frame_offset_seconds: frame?.offsetSeconds ?? (offset ? Number(offset) : null),
    }));
    data.set('photo', photo);
    onUpload(data);
  }}>
    <h3>Attach a photo or extracted video frame</h3>
    {recorded && <RecordedFramePicker disabled={busy} onFrame={setFrame} onClipChanged={() => setFrame(null)}/>}
    {frame && <figure style={{ margin: 0, width: '100%' }}>
      {preview && <img src={preview} alt="Captured frame to attach" style={{ maxWidth: '100%', maxHeight: 280 }}/>}
      <figcaption>Video offset {frame.offsetSeconds} s</figcaption>
    </figure>}
    <label>{frame ? 'Or choose a still image' : 'Image'}<input required={!frame} type="file"
      accept="image/jpeg,image/png,image/webp" onChange={event => {
        setImage(event.target.files?.[0] ?? null);
        setFrame(null);
      }}/></label>
    <label>Source URL<input type="url" required={recorded} value={source} onChange={event => setSource(event.target.value)}/></label>
    <label>Credits and reuse terms<input required maxLength={1000} value={rights} onChange={event => setRights(event.target.value)}/></label>
    <label>Evidence description<input required maxLength={2000} value={description}
      onChange={event => setDescription(event.target.value)}/></label>
    <label>Actual capture time · leave unknown if unavailable<input type="datetime-local" required={!recorded}
      value={captureTime} onChange={event => setCaptureTime(event.target.value)}
      onInput={event => setCaptureTime(event.currentTarget.value)}/></label>
    <label>Video offset · seconds<input type="number" min="0" step="any" readOnly={Boolean(frame)}
      value={frame?.offsetSeconds ?? offset} onChange={event => setOffset(event.target.value)}/></label>
    <button disabled={busy || !(frame || image) || !description.trim() || !rights.trim()}>Attach evidence</button>
  </form>;
}
