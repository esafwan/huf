/**
 * Export options and file naming for artifacts. Server conversions
 * (pdf/docx/html) exist only for document/markdown; every other type offers
 * "Download source" as a client Blob.
 */

export type ServerExportFormat = 'pdf' | 'docx' | 'html';

export interface ExportOption {
	id: ServerExportFormat | 'source';
	label: string;
}

const SOURCE_EXT: Record<string, string> = {
	html: 'html',
	svg: 'svg',
	mermaid: 'mmd',
	jsx: 'jsx',
	chart: 'jsx',
	markdown: 'md',
	document: 'md',
};

const LANG_EXT: Record<string, string> = {
	javascript: 'js', js: 'js', typescript: 'ts', ts: 'ts', python: 'py', py: 'py',
	ruby: 'rb', rust: 'rs', go: 'go', golang: 'go', java: 'java', csharp: 'cs',
	cpp: 'cpp', c: 'c', html: 'html', css: 'css', json: 'json', yaml: 'yml',
	yml: 'yml', markdown: 'md', sql: 'sql', bash: 'sh', shell: 'sh', sh: 'sh',
	tsx: 'tsx', jsx: 'jsx',
};

export function isDocumentLike(type: string): boolean {
	return type === 'document' || type === 'markdown';
}

export function exportOptionsFor(type: string): ExportOption[] {
	const source: ExportOption = { id: 'source', label: 'Download source' };
	if (isDocumentLike(type)) {
		return [
			{ id: 'pdf', label: 'PDF' },
			{ id: 'docx', label: 'Word (.docx)' },
			{ id: 'html', label: 'HTML' },
			source,
		];
	}
	if (['html', 'svg', 'mermaid', 'jsx', 'chart', 'code', 'react-component'].includes(type)) {
		return [source];
	}
	return [];
}

export function sanitizeExportStem(title: string | undefined, fallback = 'artifact'): string {
	const stem = (title ?? '')
		.replace(/[^a-z0-9]+/gi, '_')
		.replace(/^_+|_+$/g, '')
		.slice(0, 80);
	return stem || fallback;
}

export function sourceExtension(type: string, language?: string): string {
	if (type === 'code' || type === 'react-component') {
		const lang = (language ?? '').toLowerCase();
		return LANG_EXT[lang] || (lang && /^[a-z0-9]{1,6}$/.test(lang) ? lang : 'txt');
	}
	return SOURCE_EXT[type] ?? 'txt';
}

export function exportFileName(
	artifact: { type: string; title?: string; language?: string },
	ext?: string
): string {
	return `${sanitizeExportStem(artifact.title)}.${ext ?? sourceExtension(artifact.type, artifact.language)}`;
}

export function downloadSource(artifact: {
	type: string;
	title?: string;
	language?: string;
	content: string;
}): void {
	const blob = new Blob([artifact.content], { type: 'text/plain' });
	const url = URL.createObjectURL(blob);
	const a = document.createElement('a');
	a.href = url;
	a.download = exportFileName(artifact);
	a.click();
	URL.revokeObjectURL(url);
}
