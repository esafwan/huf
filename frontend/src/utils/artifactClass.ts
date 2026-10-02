/**
 * Decides whether a parsed artifact renders as a compact card in the chat
 * stream (body lives in the right pane) or stays inline.
 */
import type { ParsedArtifact } from '@/types/artifact.types';
import { parseUploadedOutput, uploadedSubtitle } from '@/utils/uploadedOutput';

/** code/mermaid artifacts with MORE lines than this render as a card. */
export const CARD_LINE_THRESHOLD = 15;

const ALWAYS_CARD = new Set(['document', 'markdown', 'html', 'chart', 'jsx', 'svg']);
const CARD_WHEN_LONG = new Set(['code', 'react-component', 'mermaid']);

export function countLines(content: string): number {
	const trimmed = (content ?? '').replace(/\s+$/, '');
	return trimmed === '' ? 0 : trimmed.split('\n').length;
}

export function isCardArtifact(artifact: Pick<ParsedArtifact, 'type' | 'content'>): boolean {
	if (ALWAYS_CARD.has(artifact.type)) return true;
	if (artifact.type === 'image') return parseUploadedOutput(artifact.content) !== null;
	if (CARD_WHEN_LONG.has(artifact.type)) return countLines(artifact.content) > CARD_LINE_THRESHOLD;
	return false;
}

/** One-line card subtitle: type label plus size hint. */
export function artifactSubtitle(artifact: Pick<ParsedArtifact, 'type' | 'content' | 'language'>): string {
	const uploaded = parseUploadedOutput(artifact.content);
	if (uploaded) return uploadedSubtitle(uploaded);
	const lines = countLines(artifact.content);
	const lineLabel = `${lines} ${lines === 1 ? 'line' : 'lines'}`;
	switch (artifact.type) {
		case 'document':
		case 'markdown':
			return `Document · ${lineLabel}`;
		case 'html':
			return `HTML page · ${lineLabel}`;
		case 'chart':
			return 'Chart';
		case 'jsx':
			return 'Interactive component';
		case 'svg':
			return 'SVG image';
		case 'mermaid':
			return `Diagram · ${lineLabel}`;
		default:
			return `${artifact.language ? `${artifact.language} · ` : ''}${lineLabel}`;
	}
}
