import { describe, expect, it } from 'vitest';
import { CARD_LINE_THRESHOLD, countLines, isCardArtifact } from './artifactClass';

const lines = (n: number) => Array.from({ length: n }, (_, i) => `l${i}`).join('\n');

describe('isCardArtifact', () => {
	it.each(['document', 'markdown', 'html', 'chart', 'jsx', 'svg'] as const)('%s is always a card', (type) => {
		expect(isCardArtifact({ type, content: 'x' })).toBe(true);
	});

	it('renders code and mermaid inline at or below the threshold', () => {
		expect(isCardArtifact({ type: 'code', content: lines(CARD_LINE_THRESHOLD) })).toBe(false);
		expect(isCardArtifact({ type: 'mermaid', content: lines(3) })).toBe(false);
	});

	it('renders code and mermaid as a card above the threshold', () => {
		expect(isCardArtifact({ type: 'code', content: lines(CARD_LINE_THRESHOLD + 1) })).toBe(true);
		expect(isCardArtifact({ type: 'mermaid', content: lines(CARD_LINE_THRESHOLD + 1) })).toBe(true);
	});

	it('keeps video and frappe views inline', () => {
		expect(isCardArtifact({ type: 'video', content: 'u' })).toBe(false);
		expect(isCardArtifact({ type: 'frappe-list', content: lines(50) })).toBe(false);
	});

	it('ignores trailing whitespace when counting lines', () => {
		expect(countLines('a\nb\n\n')).toBe(2);
		expect(countLines('')).toBe(0);
	});
});
