import { useCallback, useReducer, useState } from 'react';
import type { ParsedArtifact } from '@/types/artifact.types';

/** A durable (server-owned) artifact row, addressed by its Artifact name. */
export interface DurableArtifactTarget {
  kind: 'durable';
  name: string;
  title?: string;
  artifact_type: string;
}

/**
 * An artifact parsed from a message in the browser. Carries its content so it
 * can open before/without a durable row; `durableName` links it to the row
 * when the (message, ordinal) lookup found one (needed for server exports).
 */
export interface ParsedArtifactTarget {
  kind: 'parsed';
  key: string;
  artifact: ParsedArtifact;
  durableName?: string;
}

export type ArtifactPaneTarget = DurableArtifactTarget | ParsedArtifactTarget;

export function durableTarget(item: {
  name: string;
  title?: string;
  artifact_type: string;
}): DurableArtifactTarget {
  return { kind: 'durable', name: item.name, title: item.title, artifact_type: item.artifact_type };
}

export function targetTitle(t: ArtifactPaneTarget): string | undefined {
  return t.kind === 'durable' ? t.title : t.artifact.title;
}

export function targetType(t: ArtifactPaneTarget): string {
  return t.kind === 'durable' ? t.artifact_type : t.artifact.type;
}

export function targetDurableName(t: ArtifactPaneTarget): string | undefined {
  return t.kind === 'durable' ? t.name : t.durableName;
}

/** True when both targets point at the same artifact (parsed targets match their durable row). */
export function sameTarget(a: ArtifactPaneTarget | null, b: ArtifactPaneTarget | null): boolean {
  if (!a || !b) return false;
  if (a.kind === 'durable' && b.kind === 'durable') return a.name === b.name;
  if (a.kind === 'parsed' && b.kind === 'parsed') {
    return a.key === b.key || (!!a.durableName && a.durableName === b.durableName);
  }
  const parsed = a.kind === 'parsed' ? a : (b as ParsedArtifactTarget);
  const durable = a.kind === 'durable' ? a : (b as DurableArtifactTarget);
  return parsed.durableName === durable.name;
}

export type PaneAction =
  | { type: 'open'; target: ArtifactPaneTarget }
  | { type: 'toggle'; target: ArtifactPaneTarget }
  | { type: 'close' };

export function paneReducer(
  state: ArtifactPaneTarget | null,
  action: PaneAction
): ArtifactPaneTarget | null {
  switch (action.type) {
    case 'open':
      return action.target;
    case 'toggle':
      return sameTarget(state, action.target) ? null : action.target;
    case 'close':
      return null;
  }
}

const WIDTH_STORAGE_KEY = 'huf-artifact-pane-width';
// 42vw per design spec section 28.2.
const DEFAULT_WIDTH_VW = 42;
const MIN_WIDTH_VW = 30;
const MAX_WIDTH_VW = 75;

function clampWidth(px: number): number {
  const min = (MIN_WIDTH_VW / 100) * window.innerWidth;
  const max = (MAX_WIDTH_VW / 100) * window.innerWidth;
  return Math.min(Math.max(px, min), max);
}

function readStoredWidth(): number {
  if (typeof window === 'undefined') {
    // No viewport to size against; the first client render re-reads this.
    return 0;
  }
  try {
    const raw = window.localStorage.getItem(WIDTH_STORAGE_KEY);
    const parsed = raw ? Number(raw) : NaN;
    if (!Number.isFinite(parsed) || parsed <= 0) {
      return (DEFAULT_WIDTH_VW / 100) * window.innerWidth;
    }
    return clampWidth(parsed);
  } catch {
    return (DEFAULT_WIDTH_VW / 100) * window.innerWidth;
  }
}

export interface UseArtifactPaneResult {
  isOpen: boolean;
  currentArtifact: ArtifactPaneTarget | null;
  open: (artifact: ArtifactPaneTarget) => void;
  /** Opens the target, or closes the pane when it is already showing it (card Open/Hide). */
  toggle: (artifact: ArtifactPaneTarget) => void;
  close: () => void;
  /** Pane width in pixels, clamped to [30vw, 75vw] and persisted to localStorage. */
  width: number;
  setWidth: (px: number) => void;
}

/**
 * State for the right-docked artifact preview pane. Plain `useState` is
 * enough here — there is exactly one pane per chat page, and its state
 * (which artifact, if any) needs no persistence across reloads, unlike
 * `ArtifactsPanel`'s collapsed/expanded preference (see
 * `COLLAPSED_STORAGE_KEY` in ArtifactsPanel.tsx) — except for `width`, which
 * follows that same storage-key convention so the chosen size survives
 * reload. Host components pass `open`/`close` down to whatever should
 * trigger the pane (currently `ArtifactsPanel`'s list rows).
 */
export function useArtifactPane(): UseArtifactPaneResult {
  const [currentArtifact, dispatch] = useReducer(paneReducer, null);
  const [width, setWidthState] = useState<number>(readStoredWidth);

  const open = useCallback((artifact: ArtifactPaneTarget) => {
    dispatch({ type: 'open', target: artifact });
  }, []);

  const toggle = useCallback((artifact: ArtifactPaneTarget) => {
    dispatch({ type: 'toggle', target: artifact });
  }, []);

  const close = useCallback(() => {
    dispatch({ type: 'close' });
  }, []);

  const setWidth = useCallback((px: number) => {
    const clamped = clampWidth(px);
    setWidthState(clamped);
    try {
      window.localStorage.setItem(WIDTH_STORAGE_KEY, String(clamped));
    } catch {
      // localStorage unavailable (private mode, etc.) - preference just won't persist.
    }
  }, []);

  return {
    isOpen: currentArtifact !== null,
    currentArtifact,
    open,
    toggle,
    close,
    width,
    setWidth,
  };
}
