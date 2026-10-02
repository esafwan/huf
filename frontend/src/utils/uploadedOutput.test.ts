import { describe, expect, it } from 'vitest';
import { formatBytes, parseUploadedOutput, uploadedKind, uploadedSubtitle } from './uploadedOutput';
import { isCardArtifact, artifactSubtitle } from './artifactClass';
import { exportOptionsFor } from './artifactExport';

const ptr = (o: object) => JSON.stringify(o);
const pdf = ptr({ file_url: '/private/files/r.pdf', filename: 'r.pdf', content_type: 'application/pdf', size: 2048 });

describe('parseUploadedOutput', () => {
	it('parses a pointer', () => {
		expect(parseUploadedOutput(pdf)).toEqual({ fileUrl: '/private/files/r.pdf', filename: 'r.pdf', contentType: 'application/pdf', size: 2048 });
	});
	it.each(['', 'plain text', '{bad', '[]', '{"a":1}', '{"file_url":"javascript:alert(1)"}'])('rejects %s', (c) => {
		expect(parseUploadedOutput(c)).toBeNull();
	});
	it.each([
		'https://evil.example/x.pdf',
		'http://evil.example/x.pdf',
		'//evil.example/x.pdf',
		'/api/method/foo',
		'/other/x.pdf',
		'data:text/html,<b>x</b>',
		'/files/../private/x',
		'/files/a\\b',
		'JAVASCRIPT:alert(1)',
	])('rejects unsafe file_url %s', (u) => {
		expect(parseUploadedOutput(JSON.stringify({ file_url: u }))).toBeNull();
	});
	it('accepts /files/ and /private/files/', () => {
		expect(parseUploadedOutput('{"file_url":"/files/a.png"}')?.fileUrl).toBe('/files/a.png');
	});
	it('falls back filename to url tail', () => {
		expect(parseUploadedOutput('{"file_url":"/private/files/x.png"}')?.filename).toBe('x.png');
	});
});

describe('kinds and labels', () => {
	it('classifies', () => {
		expect(uploadedKind({ contentType: 'image/png', filename: 'a' })).toBe('image');
		expect(uploadedKind({ contentType: '', filename: 'a.xlsx' })).toBe('sheet');
		expect(uploadedKind({ contentType: '', filename: 'a.pptx' })).toBe('slides');
		expect(uploadedKind({ contentType: '', filename: 'a.bin' })).toBe('file');
	});
	it('formats size', () => {
		expect(formatBytes(0)).toBe('');
		expect(formatBytes(512)).toBe('512 B');
		expect(formatBytes(2048)).toBe('2.0 KB');
		expect(formatBytes(3 * 1024 * 1024)).toBe('3.0 MB');
	});
	it('subtitle', () => {
		expect(uploadedSubtitle(parseUploadedOutput(pdf)!)).toBe('PDF · 2.0 KB');
	});
});

describe('wiring', () => {
	it('image pointers are cards, plain image is not', () => {
		expect(isCardArtifact({ type: 'image', content: pdf })).toBe(true);
		expect(isCardArtifact({ type: 'image', content: 'x' })).toBe(false);
	});
	it('subtitle uses pointer', () => {
		expect(artifactSubtitle({ type: 'document', content: pdf })).toBe('PDF · 2.0 KB');
	});
	it('export offers file download only for pointers', () => {
		expect(exportOptionsFor('document', pdf).map((o) => o.id)).toEqual(['file']);
		expect(exportOptionsFor('document', 'hello').map((o) => o.id)).toContain('pdf');
	});
});
