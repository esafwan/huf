/**
 * ArtifactPreviewPane — right-docked pane that previews a durable document
 * artifact (any type) in place, instead of opening `/artifact/:name` in a new tab.
 *
 * This is intentionally a thin host: document rendering is delegated to
 * `DocumentPreview` (frontend/src/components/chat/DocumentPreview.tsx), which
 * already knows how to fetch and sandbox-render a saved Artifact's HTML by
 * name. This component owns the pane chrome (header, title, close button,
 * quick-switcher dropdown) and layout, plus the drag-to-resize handle on its
 * left edge.
 *
 * Visual cues and the resize mechanism are borrowed from `RightSidebar.tsx`
 * (border-l, bg-card, header + scrollable body; mouse-move drag-resize
 * pattern around RightSidebar.tsx:49,64-82) without depending on it — that
 * component is Flow Canvas-specific and unrelated to chat.
 */
import { useCallback, useEffect, useState } from 'react';
import { Loader2, X } from 'lucide-react';
import { NativeArtifactView } from '@/components/chat/NativeArtifactView';
import { ExportMenu } from '@/components/chat/artifacts/ExportMenu';
import { getArtifact } from '@/services/artifactApi';
import type { ParsedArtifact, ArtifactType } from '@/types/artifact.types';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  durableTarget,
  targetDurableName,
  targetTitle,
  targetType,
  type ArtifactPaneTarget,
} from '@/components/chat/useArtifactPane';
import type { ArtifactListItem } from '@/services/artifactPanelApi';


const NATIVE_TYPES = new Set<string>([
  'code', 'document', 'html', 'svg', 'mermaid', 'react-component', 'markdown',
  'jsx', 'chart', 'video', 'frappe-list', 'frappe-form', 'frappe-report',
]);

/**
 * Resolves a pane target to a renderable artifact: parsed targets carry their
 * content; durable targets are fetched by name (get_artifact returns content,
 * unlike get_artifact_html which is document-only).
 */
function usePaneArtifact(target: ArtifactPaneTarget | null) {
  const [fetched, setFetched] = useState<{ name: string; artifact: ParsedArtifact } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const durableName = target?.kind === 'durable' ? target.name : null;

  useEffect(() => {
    if (!durableName) return;
    let cancelled = false;
    setError(null);
    getArtifact(durableName)
      .then((doc) => {
        if (cancelled) return;
        setFetched({
          name: durableName,
          artifact: {
            id: doc.name,
            type: (NATIVE_TYPES.has(doc.artifact_type) ? doc.artifact_type : 'document') as ArtifactType,
            title: doc.title,
            language: doc.language,
            content: doc.content,
          },
        });
      })
      .catch(() => {
        if (!cancelled) setError('Unable to load this artifact.');
      });
    return () => {
      cancelled = true;
    };
  }, [durableName]);

  if (!target) return { artifact: null, loading: false, error: null };
  if (target.kind === 'parsed') {
    // Use the durable row's html endpoint for documents when it exists.
    const artifact =
      target.durableName && (target.artifact.type === 'document' || target.artifact.type === 'markdown')
        ? { ...target.artifact, id: target.durableName }
        : target.artifact;
    return { artifact, loading: false, error: null };
  }
  const artifact = fetched && fetched.name === target.name ? fetched.artifact : null;
  return { artifact, loading: !artifact && !error, error };
}

export interface ArtifactPreviewPaneProps {
  /** Artifact to preview, or null when the pane should be hidden. */
  artifact: ArtifactPaneTarget | null;
  onClose: () => void;
  /** Current pane width in px, owned by `useArtifactPane`. */
  width: number;
  onWidthChange: (px: number) => void;
  /**
   * All artifacts in the conversation (shared with `ArtifactsPanel` via
   * `useConversationArtifacts` — see ChatPageV2.tsx). Filtered here to
   * Lists every type in the quick-switcher; the pane renders each natively.
   */
  artifacts: ArtifactListItem[];
  onSelectArtifact: (artifact: ArtifactPaneTarget) => void;
}

export function ArtifactPreviewPane({
  artifact,
  onClose,
  width,
  onWidthChange,
  artifacts,
  onSelectArtifact,
}: ArtifactPreviewPaneProps) {
  const [isResizing, setIsResizing] = useState(false);
  const { artifact: resolved, loading, error } = usePaneArtifact(artifact);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
  }, []);

  useEffect(() => {
    if (!isResizing) return;
    const handleMouseMove = (e: MouseEvent) => {
      // Handle is on the pane's left edge, so width grows as the pointer
      // moves left (mirrors RightSidebar.tsx's `window.innerWidth - e.clientX`).
      onWidthChange(window.innerWidth - e.clientX);
    };
    const handleMouseUp = () => setIsResizing(false);
    // Without this, dragging the handle sweeps a text selection across the
    // chat transcript and the document preview underneath it.
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.userSelect = 'none';
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    return () => {
      document.body.style.userSelect = previousUserSelect;
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isResizing, onWidthChange]);

  if (!artifact) {
    return null;
  }

  const durableName = targetDurableName(artifact);
  const title = targetTitle(artifact);

  return (
    <div
      className="relative flex h-full shrink-0 flex-col border-l border-line bg-paper"
      style={{ width }}
    >
      <div
        className="absolute left-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-primary/50 transition-colors"
        onMouseDown={handleMouseDown}
      />

      <div className="flex h-chat-header flex-none items-center gap-2.5 border-b border-line px-3.5">
        {artifacts.length > 1 ? (
          <Select
            value={durableName ?? ''}
            onValueChange={(name) => {
              const next = artifacts.find((a) => a.name === name);
              if (next) {
                onSelectArtifact(durableTarget(next));
              }
            }}
          >
            <SelectTrigger className="h-auto min-w-0 flex-none max-w-[60%] border-none bg-transparent p-0 text-[13px] font-medium shadow-none focus:ring-0">
              <SelectValue placeholder="Artifact">
                <span className="truncate">{title || 'Artifact'}</span>
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {artifacts.map((a) => (
                <SelectItem key={a.name} value={a.name}>
                  {a.title || a.artifact_type}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <h2 className="min-w-0 flex-none max-w-[60%] truncate text-[13px] font-medium">
            {title || 'Artifact'}
          </h2>
        )}
        <span className="font-mono text-[11px] uppercase text-steel-soft">
          {targetType(artifact)}
        </span>
        <span className="flex-1" />
        {resolved && <ExportMenu artifact={resolved} durableName={durableName} />}
        <button
          type="button"
          onClick={onClose}
          aria-label="Close preview"
          className="text-steel hover:text-ink"
        >
          <X className="size-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && (
          <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading…
          </div>
        )}
        {error && <div className="p-4 text-sm text-destructive">{error}</div>}
        {resolved && (
          <div className="p-3">
            <NativeArtifactView key={durableName ?? resolved.id} artifact={resolved} />
          </div>
        )}
      </div>
    </div>
  );
}

export default ArtifactPreviewPane;
