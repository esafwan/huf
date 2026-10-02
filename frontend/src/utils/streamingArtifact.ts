/**
 * Detects an `<artifact ...>` block that is still streaming (opened, not yet
 * closed) so the chat can show a "Creating artifact..." placeholder instead
 * of leaking raw tag text.
 */
export interface StreamingArtifact {
	type?: string;
	title?: string;
	/** Content with the unfinished block removed. */
	text: string;
}

const OPEN_TAG_START = /<(?:artifact|antArtifact)(?=[\s>]|$)/gi;

export function splitStreamingArtifact(content: string): StreamingArtifact | null {
	let lastStart = -1;
	for (const m of content.matchAll(OPEN_TAG_START)) lastStart = m.index ?? -1;
	if (lastStart < 0) return null;
	const tail = content.slice(lastStart);
	if (/<\/(?:artifact|antArtifact)>/i.test(tail)) return null;
	const headEnd = tail.indexOf('>');
	const head = headEnd >= 0 ? tail.slice(0, headEnd) : tail;
	const type = /type=["']([^"']*)["']/i.exec(head)?.[1];
	const title = /title=["']([^"']*)["']/i.exec(head)?.[1];
	return { type, title, text: content.slice(0, lastStart).replace(/\s+$/, '') };
}

/** Auto-open rule: live-arrived (a streaming placeholder was seen), first artifact in its message. */
export function shouldAutoOpen(input: {
	enabled: boolean;
	isMobile: boolean;
	livePending: boolean;
	indexInMessage: number;
}): boolean {
	return input.enabled && !input.isMobile && input.livePending && input.indexInMessage === 0;
}

export const AUTO_OPEN_STORAGE_KEY = 'huf-auto-open-artifacts';

export function readAutoOpenPref(): boolean {
	try {
		return window.localStorage.getItem(AUTO_OPEN_STORAGE_KEY) !== '0';
	} catch {
		return true;
	}
}
