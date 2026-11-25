import { useEffect, useRef, useState } from 'react';

export interface RecordedFrame {
  image: File;
  offsetSeconds: number;
}

export default function RecordedFramePicker({
  disabled, onFrame, onClipChanged,
}: {
  disabled: boolean;
  onFrame: (frame: RecordedFrame) => void;
  onClipChanged: () => void;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const generation = useRef(0);
  const [source, setSource] = useState('');
  const [capturing, setCapturing] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => () => {
    if (source) URL.revokeObjectURL(source);
  }, [source]);
  useEffect(() => () => { generation.current += 1; }, []);

  function capture() {
    const clip = video.current;
    if (!clip || !clip.paused || clip.seeking || clip.readyState < 2 ||
        !clip.videoWidth || !clip.videoHeight || !Number.isFinite(clip.currentTime)) {
      setError('Pause on a visible frame and wait for the clip to finish seeking.');
      return;
    }
    setError('');
    const offsetSeconds = Math.round(clip.currentTime * 1000) / 1000;
    const canvas = document.createElement('canvas');
    const scale = Math.min(1, 1920 / Math.max(clip.videoWidth, clip.videoHeight));
    canvas.width = Math.max(1, Math.round(clip.videoWidth * scale));
    canvas.height = Math.max(1, Math.round(clip.videoHeight * scale));
    const context = canvas.getContext('2d');
    if (!context) {
      setError('This browser could not extract a frame. You can attach a still image below.');
      return;
    }
    const current = ++generation.current;
    try {
      context.drawImage(clip, 0, 0, canvas.width, canvas.height);
      setCapturing(true);
      canvas.toBlob(blob => {
        if (current !== generation.current) return;
        setCapturing(false);
        if (!blob) {
          setError('The frame could not be saved. Try another frame.');
          return;
        }
        onFrame({ image: new File([blob], 'recorded-clip-frame.jpg', { type: 'image/jpeg' }), offsetSeconds });
      }, 'image/jpeg', 0.92);
    } catch {
      setCapturing(false);
      setError('The frame could not be saved. Try another frame.');
    }
  }

  return <div style={{ width: '100%' }}>
    <label>Choose a recorded clip<input type="file" accept="video/*" disabled={disabled} onChange={event => {
      generation.current += 1;
      const file = event.target.files?.[0];
      setSource(file ? URL.createObjectURL(file) : '');
      setCapturing(false);
      setError('');
      onClipChanged();
    }}/></label>
    {source && <>
      <video key={source} ref={video} controls preload="metadata" src={source}
        style={{ maxWidth: '100%', display: 'block', marginTop: 12 }}
        onError={() => setError('This clip could not be played. Choose a browser-supported video.')}/>
      <p className="lj-muted">Pause at the observation and capture a still. The clip stays on this device.</p>
      <button type="button" className="secondary" disabled={disabled || capturing} onClick={capture}>
        Capture paused frame
      </button>
    </>}
    {error && <p role="alert">{error}</p>}
  </div>;
}
