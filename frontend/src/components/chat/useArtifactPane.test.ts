import { describe, expect, it } from 'vitest';
import { durableTarget, paneReducer, sameTarget, type ParsedArtifactTarget } from './useArtifactPane';

const parsed = (key: string, durableName?: string): ParsedArtifactTarget => ({
	kind: 'parsed',
	key,
	durableName,
	artifact: { id: 'x', type: 'html', content: '<p/>' },
});
const durable = durableTarget({ name: 'ART-1', artifact_type: 'html' });

describe('paneReducer', () => {
	it('opens, replaces and closes', () => {
		let s = paneReducer(null, { type: 'open', target: durable });
		expect(s).toBe(durable);
		const next = parsed('m:0');
		s = paneReducer(s, { type: 'open', target: next });
		expect(s).toBe(next);
		expect(paneReducer(s, { type: 'close' })).toBeNull();
	});

	it('toggle hides the artifact already shown and opens a different one', () => {
		const a = parsed('m:0');
		expect(paneReducer(a, { type: 'toggle', target: parsed('m:0') })).toBeNull();
		const b = parsed('m:1');
		expect(paneReducer(a, { type: 'toggle', target: b })).toBe(b);
	});
});

describe('sameTarget', () => {
	it('links a parsed target to its durable row', () => {
		expect(sameTarget(parsed('m:0', 'ART-1'), durable)).toBe(true);
		expect(sameTarget(durable, parsed('m:0', 'ART-1'))).toBe(true);
		expect(sameTarget(parsed('m:0'), durable)).toBe(false);
	});
	it('is false for null', () => {
		expect(sameTarget(null, durable)).toBe(false);
	});
});
