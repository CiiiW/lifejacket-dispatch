/**
 * Map-first layout for the Rescue network page: the Triage map on the left, and
 * on the right either the case list or the selected case. Every case comes from
 * the permissioned `/network/cases` API through `rows`; nothing here fetches.
 */

import { useCallback, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

import TriageMap from '../components/TriageMap.web';
import { severityColour } from '../lib/api';
import type { NetworkCase } from '../lib/networkApi';
import { toMapPin } from '../lib/networkPins';

const PANEL_DEFAULT_WIDTH = 400;
const PANEL_MIN_WIDTH = 320;
const MAP_MIN_WIDTH = 360;
const PANEL_KEY_STEP = 24;
const NO_CENTRES: never[] = [];

// The page styles every <button> as a large accent button, which would swallow
// the map's own zoom controls. Put them back to the map library's look.
const mapControlCss = `
.lj-network .maplibregl-ctrl-group button{width:29px;height:29px;padding:0;border:0;border-radius:0;background-color:transparent}
.lj-network .maplibregl-ctrl-group button:not(:disabled):hover{background-color:rgba(0,0,0,.05)}
.lj-network .maplibregl-ctrl-attrib button{width:24px;height:24px;padding:0;border:0;background-color:transparent}
`;

const words = (value: string | null) => (value ? value.replace(/_/g, ' ') : 'Not provided');

export default function NetworkMapView({
  rows,
  selected,
  onSelect,
  detail,
  truncatedAt,
}: {
  rows: NetworkCase[];
  selected: string | null;
  onSelect: (id: string | null) => void;
  /** The permissioned case detail, shown in place of the list. */
  detail: ReactNode;
  /** Set when more cases exist than were loaded onto the map. */
  truncatedAt: number | null;
}) {
  const pins = useMemo(() => rows.map(toMapPin), [rows]);
  const [panelWidth, setPanelWidth] = useState(PANEL_DEFAULT_WIDTH);
  const [expanded, setExpanded] = useState(false);
  const [dragging, setDragging] = useState(false);

  const clamp = useCallback(
    (width: number) =>
      Math.max(PANEL_MIN_WIDTH, Math.min(width, window.innerWidth - MAP_MIN_WIDTH)),
    [],
  );

  // Dragging left widens the panel. Listeners sit on `window` so the drag keeps
  // tracking over the map canvas, which would otherwise swallow the events.
  const startDrag = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      const startX = event.clientX;
      const startWidth = panelWidth;
      const previousSelect = document.body.style.userSelect;
      document.body.style.userSelect = 'none';
      setDragging(true);
      const move = (e: PointerEvent) => setPanelWidth(clamp(startWidth - (e.clientX - startX)));
      const stop = () => {
        setDragging(false);
        document.body.style.userSelect = previousSelect;
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', stop);
        window.removeEventListener('pointercancel', stop);
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', stop);
      window.addEventListener('pointercancel', stop);
    },
    [panelWidth, clamp],
  );

  const dividerKey = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key === 'ArrowLeft') setPanelWidth((w) => clamp(w + PANEL_KEY_STEP));
      else if (event.key === 'ArrowRight') setPanelWidth((w) => clamp(w - PANEL_KEY_STEP));
      else return;
      event.preventDefault();
    },
    [clamp],
  );

  return (
    <>
    <style>{mapControlCss}</style>
    <div
      style={{
        display: 'flex',
        height: 'calc(100vh - 260px)',
        minHeight: 520,
        border: '1px solid #ffffff20',
        borderRadius: 14,
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          position: 'relative',
          flex: 1,
          minWidth: MAP_MIN_WIDTH,
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <TriageMap
          pins={pins}
          centres={NO_CENTRES}
          route={null}
          density={null}
          showDensity={false}
          selectedId={selected}
          onSelect={onSelect}
          popup={false}
        />
        <button
          className="secondary"
          style={{ position: 'absolute', top: 12, left: 12, zIndex: 5, background: '#0b132b' }}
          aria-label={expanded ? 'Show case list' : 'Expand map'}
          onClick={() => setExpanded((current) => !current)}
        >
          {expanded ? 'Show list' : 'Expand map'}
        </button>
      </div>

      {!expanded && (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize map and case panel"
          aria-valuenow={panelWidth}
          tabIndex={0}
          onPointerDown={startDrag}
          onKeyDown={dividerKey}
          onDoubleClick={() => setPanelWidth(PANEL_DEFAULT_WIDTH)}
          title="Drag to resize · double-click to reset"
          style={{
            flex: '0 0 8px',
            cursor: 'col-resize',
            touchAction: 'none',
            background: dragging ? '#48cae4' : '#ffffff20',
          }}
        />
      )}

      {/* Kept mounted but hidden while expanded so scroll position survives. */}
      <aside
        aria-label="Cases"
        style={{
          display: expanded ? 'none' : 'block',
          flex: `0 0 ${panelWidth}px`,
          width: panelWidth,
          overflowY: 'auto',
          padding: 16,
          background: '#101a38',
        }}
      >
        {selected ? (
          <>
            <button className="secondary" style={{ marginBottom: 12 }} onClick={() => onSelect(null)}>
              ‹ All cases
            </button>
            {detail}
          </>
        ) : (
          <>
            <h2>
              {rows.length} {rows.length === 1 ? 'case' : 'cases'}
            </h2>
            {truncatedAt !== null && (
              <p className="lj-notice">
                Showing the first {truncatedAt.toLocaleString()} cases. Choose a narrower view to
                see the rest.
              </p>
            )}
            {rows.length ? (
              <div className="lj-cases">
                {rows.map((row) => (
                  <button
                    className="lj-case"
                    key={row.incident_id}
                    aria-pressed={selected === row.incident_id}
                    style={{ borderLeft: `4px solid ${severityColour(row.severity_level)}` }}
                    onClick={() => onSelect(row.incident_id)}
                  >
                    <strong>{words(row.species_common_name ?? row.animal_group)}</strong>
                    <span className="lj-id">Case {row.incident_id}</span>
                    <div className="lj-meta">
                      <span>{row.state_code ?? 'State under review'}</span>
                      <span>{words(row.status)}</span>
                      <span>{words(row.severity_level)}</span>
                    </div>
                  </button>
                ))}
              </div>
            ) : (
              <div className="lj-panel">
                <h2>No cases in this view</h2>
                <p className="lj-muted">
                  Try another filter or refresh later. Only cases available to your verified
                  account appear here.
                </p>
              </div>
            )}
          </>
        )}
      </aside>
    </div>
    </>
  );
}
