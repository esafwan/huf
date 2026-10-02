/**
 * Compact in-chat card for artifact-class outputs: type tile, title, one-line
 * subtitle, Open/Hide toggle (reflects "currently in the pane") and Export.
 * The body renders only in the right pane (or /artifact/:name on mobile).
 */
import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { getArtifactIcon } from '@/components/chat/ArtifactsPanel';
import { ExportMenu } from '@/components/chat/artifacts/ExportMenu';
import { useArtifactPaneContext } from '@/components/chat/artifacts/ArtifactPaneContext';
import { sameTarget, type ParsedArtifactTarget } from '@/components/chat/useArtifactPane';
import { artifactSubtitle } from '@/utils/artifactClass';
import { findDurableArtifact, parsedArtifactKey } from '@/utils/artifactIdentity';
import { shouldAutoOpen } from '@/utils/streamingArtifact';
import { writePreviewCache } from '@/utils/previewCache';
import type { ParsedArtifact } from '@/types/artifact.types';

export interface ArtifactCardProps {
	artifact: ParsedArtifact;
	messageId: string;
	/** Server message_index of this tag, or -1 when it has no durable row. */
	ordinal: number;
	/** Position among the artifact tags of this message (0 = first). */
	indexInMessage: number;
}

export function ArtifactCard({ artifact, messageId, ordinal, indexInMessage }: ArtifactCardProps) {
	const ctx = useArtifactPaneContext();
	const navigate = useNavigate();
	const durable = ctx ? findDurableArtifact(ctx.durableArtifacts, messageId, ordinal) : undefined;
	const target: ParsedArtifactTarget = {
		kind: 'parsed',
		key: parsedArtifactKey(messageId, ordinal, indexInMessage),
		artifact,
		durableName: durable?.name,
	};
	const isActive = sameTarget(ctx?.activeTarget ?? null, target);

	const autoOpened = useRef(false);
	useEffect(() => {
		if (!ctx || autoOpened.current) return;
		autoOpened.current = true;
		const live = ctx.consumeLive();
		if (
			shouldAutoOpen({
				enabled: ctx.autoOpen,
				isMobile: ctx.isMobile,
				livePending: live,
				indexInMessage,
			})
		) {
			ctx.open(target);
		}
		// Mount-only: auto-open must not re-fire on re-render or streaming updates.
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, []);

	const Icon = getArtifactIcon(artifact.type === 'react-component' ? 'code' : artifact.type);

	const handleClick = () => {
		if (!ctx) return;
		if (ctx.isMobile) {
			if (durable) {
				navigate(`/artifact/${durable.name}`);
			} else {
				writePreviewCache(messageId, {
					textContent: '',
					jsxPreviews: [],
					webPreviews: [],
					artifacts: [artifact],
				});
				navigate(`/view/${messageId}`);
			}
			return;
		}
		ctx.toggle(target);
	};

	return (
		<div
			data-testid="artifact-card"
			className="my-3 flex items-center gap-3 rounded-md border border-line bg-paper p-2.5"
		>
			<div className="flex size-9 shrink-0 items-center justify-center rounded-sm bg-paper-deep text-steel">
				<Icon className="size-[18px]" />
			</div>
			<div className="min-w-0 flex-1">
				<div className="truncate text-[13px] font-medium text-ink">
					{artifact.title || `${artifact.type} artifact`}
				</div>
				<div className="truncate text-[12px] text-steel">{artifactSubtitle(artifact)}</div>
			</div>
			<ExportMenu artifact={artifact} durableName={durable?.name} />
			<Button type="button" size="sm" variant="outline" onClick={handleClick}>
				{isActive ? 'Hide' : 'Open'}
			</Button>
		</div>
	);
}

/** Placeholder shown while an `<artifact>` tag is still streaming in. */
export function ArtifactStreamingCard({ type, title }: { type?: string; title?: string }) {
	const ctx = useArtifactPaneContext();
	useEffect(() => {
		ctx?.markLive();
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, []);
	return (
		<div
			data-testid="artifact-streaming-card"
			className="my-3 flex items-center gap-3 rounded-md border border-line bg-paper p-2.5 text-[13px] text-steel"
		>
			<Loader2 className="size-4 animate-spin" />
			<span className="truncate">Creating {title || type || 'artifact'}…</span>
		</div>
	);
}
