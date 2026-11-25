import { useEffect, useState } from 'react';
import type { Turn } from '../../../shared/api';
import { summariseConditions } from '../../../shared/conditions';

export function AnimalChoice({ turn, file, busy, onChoose }: {
  turn: Turn;
  file: File | null;
  busy: boolean;
  onChoose: (number: number) => void;
}) {
  const [preview, setPreview] = useState<{ file: File; url: string } | null>(null);
  const [loadedUrl, setLoadedUrl] = useState('');
  useEffect(() => {
    if (!file) return;
    const url = URL.createObjectURL(file);
    setPreview({ file, url });
    return () => URL.revokeObjectURL(url);
  }, [file]);
  const url = preview?.file === file ? preview?.url : undefined;
  const required = turn.action === 'ask_which_animal';
  const choices = <>
    {url && <div className="animal-photo">
      <img src={url} alt="Your uploaded animal photo" onLoad={() => setLoadedUrl(url)} hidden={loadedUrl !== url} />
      {loadedUrl === url && turn.detections.map((animal, index) => {
        const [top, left, bottom, right] = animal.box;
        if (![top,left,bottom,right].every(n=>Number.isFinite(n) && n>=0 && n<=1000) || bottom<=top || right<=left) return null;
        return <button key={index} type="button" className="animal-box" disabled={busy}
          aria-label={`Select animal ${index + 1} on the photo`}
          style={{ top: `${top/10}%`, left: `${left/10}%`, width: `${(right-left)/10}%`, height: `${(bottom-top)/10}%` }}
          onClick={() => onChoose(index + 1)}>{index + 1}</button>;
      })}
    </div>}
    <div className="toolbar">{turn.detections.map((animal, index) =>
      <button type="button" key={index} className="secondary" disabled={busy || turn.selected_detection===index}
        onClick={() => onChoose(index + 1)}>{index + 1}. {animal.description || animal.kind}</button>)}
    </div>
  </>;
  return required ? choices : <details><summary>Change the animal in the photo</summary>{choices}</details>;
}

export function ReportGuidance({ turn }: { turn: Turn }) {
  const conditions = turn.conditions ? summariseConditions(turn.conditions) : '';
  if (!turn.reporter_instructions.length && !turn.injury_summary &&
      !turn.severity_level && !conditions && !turn.report_headline) return null;
  return <details open={turn.complete}>
    <summary>{turn.complete ? 'Guidance and conditions' : 'Guidance so far'}</summary>
    {turn.report_headline && <p><strong>{turn.report_headline}</strong></p>}
    {turn.injury_summary && <p>{turn.injury_summary}</p>}
    {turn.severity_level && <p>Suggested urgency · {turn.severity_level.replaceAll('_', ' ')}</p>}
    {turn.severity_reasons.length > 0 && <ul>{turn.severity_reasons.map((reason,index)=><li key={index}>{reason}</li>)}</ul>}
    {turn.reporter_instructions.length > 0 && <ol>{turn.reporter_instructions.map((step,index)=><li key={index}>{step}</li>)}</ol>}
    {conditions && <p><strong>Local conditions</strong> · {conditions}</p>}
    {turn.environmental_rationale && <p>{turn.environmental_rationale}</p>}
  </details>;
}
