import { describe, expect, it } from 'vitest';
import { exportFileName, exportOptionsFor, sanitizeExportStem, sourceExtension } from './artifactExport';

describe('artifact export', () => {
	it('offers conversions only for documents', () => {
		expect(exportOptionsFor('document').map((o) => o.id)).toEqual(['pdf', 'docx', 'html', 'source']);
		expect(exportOptionsFor('markdown').map((o) => o.id)).toContain('pdf');
		expect(exportOptionsFor('chart').map((o) => o.id)).toEqual(['source']);
		expect(exportOptionsFor('code').map((o) => o.id)).toEqual(['source']);
		expect(exportOptionsFor('video')).toEqual([]);
	});

	it('sanitizes titles into file stems', () => {
		expect(sanitizeExportStem('Q3 Report: Final!')).toBe('Q3_Report_Final');
		expect(sanitizeExportStem('   ')).toBe('artifact');
		expect(sanitizeExportStem(undefined, 'x')).toBe('x');
	});

	it('picks source extensions by type and language', () => {
		expect(sourceExtension('html')).toBe('html');
		expect(sourceExtension('mermaid')).toBe('mmd');
		expect(sourceExtension('chart')).toBe('jsx');
		expect(sourceExtension('code', 'python')).toBe('py');
		expect(sourceExtension('code', 'weird lang!')).toBe('txt');
		expect(exportFileName({ type: 'svg', title: 'My Logo' })).toBe('My_Logo.svg');
	});
});
