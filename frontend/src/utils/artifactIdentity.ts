/**
 * Maps a client-parsed `<artifact>` tag to its durable server row.
 *
 * Server identity is `(message, message_index)` where message_index is the
 * ordinal of the block in document order across <artifact>/<antArtifact>,
 * <web-preview> and <jsx-preview> tags, skipping blocks with empty bodies
 * (huf/ai/artifact_extraction.py::parse_artifacts). `artifactOrdinals` mirrors
 * that rule so the client never depends on its throwaway parse ids.
 */
import type { ArtifactListItem } from '@/services/artifactPanelApi';

const ARTIFACT_RE = /<(?:artifact|antArtifact)\s+([^>]*)>([\s\S]*?)<\/(?:artifact|antArtifact)>/gi;
const WEB_PREVIEW_RE = /<web-preview\s+([^>]*?)\s*(?:\/>|><\/web-preview>)/gi;
const JSX_PREVIEW_RE = /<jsx-preview\s*([^>]*?)>(?:([\s\S]*?)<\/jsx-preview>|(?:\/>))/gi;
const ATTR_RE = /(\w+)=["']([^"']*)["']/g;

function attrs(raw: string): Record<string, string> {
	const out: Record<string, string> = {};
	for (const m of (raw || '').matchAll(ATTR_RE)) out[m[1]] = m[2];
	return out;
}

/**
 * For each `<artifact>` tag in `content` (document order) returns its server
 * message_index, or -1 when the server would skip it (empty body).
 */
export function artifactOrdinals(content: string): number[] {
	type Block = { start: number; isArtifact: boolean; nonEmpty: boolean };
	const blocks: Block[] = [];
	for (const m of content.matchAll(ARTIFACT_RE)) {
		blocks.push({ start: m.index ?? 0, isArtifact: true, nonEmpty: (m[2] ?? '').trim() !== '' });
	}
	for (const m of content.matchAll(WEB_PREVIEW_RE)) {
		blocks.push({ start: m.index ?? 0, isArtifact: false, nonEmpty: !!attrs(m[1]).url });
	}
	for (const m of content.matchAll(JSX_PREVIEW_RE)) {
		const body = m[2] !== undefined ? m[2] : attrs(m[1]).jsx || '';
		blocks.push({ start: m.index ?? 0, isArtifact: false, nonEmpty: body.trim() !== '' });
	}
	blocks.sort((a, b) => a.start - b.start);
	const result: number[] = [];
	let ordinal = 0;
	for (const b of blocks) {
		if (!b.nonEmpty) {
			if (b.isArtifact) result.push(-1);
			continue;
		}
		if (b.isArtifact) result.push(ordinal);
		ordinal++;
	}
	return result;
}

export function findDurableArtifact(
	artifacts: ArtifactListItem[],
	messageId: string,
	ordinal: number
): ArtifactListItem | undefined {
	if (ordinal < 0) return undefined;
	return artifacts.find((a) => a.message === messageId && a.message_index === ordinal);
}

export function parsedArtifactKey(messageId: string, ordinal: number, indexInMessage: number): string {
	return `${messageId}:${ordinal >= 0 ? ordinal : `p${indexInMessage}`}`;
}
