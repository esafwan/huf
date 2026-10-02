import { describe, expect, it } from 'vitest';
import { artifactOrdinals, findDurableArtifact, parsedArtifactKey } from './artifactIdentity';
import type { ArtifactListItem } from '@/services/artifactPanelApi';

const row = (name: string, message: string, message_index: number): ArtifactListItem => ({
	name, message, message_index, artifact_type: 'document', size_bytes: 1, creation: '',
});

describe('artifactOrdinals', () => {
	it('numbers artifact tags in document order', () => {
		const c = 'a <artifact type="code">x</artifact> b <artifact type="html">y</artifact>';
		expect(artifactOrdinals(c)).toEqual([0, 1]);
	});

	it('counts jsx and web previews in the shared ordinal space like the server', () => {
		const c =
			'<jsx-preview title="t">jsx body</jsx-preview><web-preview url="http://x" /><artifact type="code">x</artifact>';
		expect(artifactOrdinals(c)).toEqual([2]);
	});

	it('skips empty bodies without consuming an ordinal', () => {
		const c = '<artifact type="code">  </artifact><artifact type="code">x</artifact>';
		expect(artifactOrdinals(c)).toEqual([-1, 0]);
	});
});

describe('findDurableArtifact', () => {
	const rows = [row('A1', 'm1', 0), row('A2', 'm1', 1), row('A3', 'm2', 0)];
	it('matches by (message, ordinal)', () => {
		expect(findDurableArtifact(rows, 'm1', 1)?.name).toBe('A2');
		expect(findDurableArtifact(rows, 'm2', 0)?.name).toBe('A3');
	});
	it('returns undefined for unknown or skipped ordinals', () => {
		expect(findDurableArtifact(rows, 'm3', 0)).toBeUndefined();
		expect(findDurableArtifact(rows, 'm1', -1)).toBeUndefined();
	});
	it('builds stable keys', () => {
		expect(parsedArtifactKey('m1', 1, 0)).toBe('m1:1');
		expect(parsedArtifactKey('m1', -1, 2)).toBe('m1:p2');
	});
});
