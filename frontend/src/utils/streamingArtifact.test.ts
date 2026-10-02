import { describe, expect, it } from 'vitest';
import { shouldAutoOpen, splitStreamingArtifact } from './streamingArtifact';

describe('splitStreamingArtifact', () => {
	it('returns null when no artifact is open', () => {
		expect(splitStreamingArtifact('hello')).toBeNull();
		expect(splitStreamingArtifact('<artifact type="code">x</artifact> done')).toBeNull();
	});

	it('strips an unclosed artifact and reads type/title', () => {
		const r = splitStreamingArtifact('Intro\n<artifact type="html" title="Page">partial');
		expect(r).toEqual({ type: 'html', title: 'Page', text: 'Intro' });
	});

	it('handles a half-written opening tag', () => {
		expect(splitStreamingArtifact('Hi <artifact typ')?.text).toBe('Hi');
	});

	it('only treats the last block as streaming', () => {
		const r = splitStreamingArtifact('<artifact type="code">a</artifact> <artifact type="svg">b');
		expect(r?.type).toBe('svg');
		expect(r?.text).toContain('</artifact>');
	});
});

describe('shouldAutoOpen', () => {
	const base = { enabled: true, isMobile: false, livePending: true, indexInMessage: 0 };
	it('opens the first live artifact on desktop', () => {
		expect(shouldAutoOpen(base)).toBe(true);
	});
	it.each([
		{ enabled: false },
		{ isMobile: true },
		{ livePending: false },
		{ indexInMessage: 1 },
	])('does not open when %o', (override) => {
		expect(shouldAutoOpen({ ...base, ...override })).toBe(false);
	});
});
