/**
 * Uploaded desktop outputs: binary files (pdf/docx/xlsx/pptx/png/jpg) are
 * attached to the Artifact as a private File and the Artifact content is a
 * JSON pointer (huf/ai/desktop_outputs.py).
 */
export interface UploadedOutput {
	fileUrl: string;
	filename: string;
	contentType: string;
	size: number;
}

export type UploadedKind = 'image' | 'pdf' | 'word' | 'sheet' | 'slides' | 'file';

/** Only same-origin Frappe file paths; never external, protocol-relative or javascript: URLs. */
export function isSafeFileUrl(url: string): boolean {
	if (!(url.startsWith('/private/files/') || url.startsWith('/files/'))) return false;
	// eslint-disable-next-line no-control-regex
	if (/[\x00-\x1f\\]/.test(url) || url.includes('..')) return false;
	return true;
}

export function parseUploadedOutput(content: string | undefined | null): UploadedOutput | null {
	if (!content || content.charCodeAt(0) !== 123 /* { */) return null;
	let raw: unknown;
	try {
		raw = JSON.parse(content);
	} catch {
		return null;
	}
	if (!raw || typeof raw !== 'object') return null;
	const o = raw as Record<string, unknown>;
	if (typeof o.file_url !== 'string' || !o.file_url) return null;
	const fileUrl = o.file_url;
	if (!isSafeFileUrl(fileUrl)) return null;
	return {
		fileUrl,
		filename: typeof o.filename === 'string' && o.filename ? o.filename : fileUrl.split('/').pop() || 'file',
		contentType: typeof o.content_type === 'string' ? o.content_type : '',
		size: typeof o.size === 'number' && o.size >= 0 ? o.size : 0,
	};
}

export function uploadedKind(o: Pick<UploadedOutput, 'contentType' | 'filename'>): UploadedKind {
	const ct = o.contentType.toLowerCase();
	const ext = (o.filename.split('.').pop() || '').toLowerCase();
	if (ct.startsWith('image/') || ['png', 'jpg', 'jpeg'].includes(ext)) return 'image';
	if (ct === 'application/pdf' || ext === 'pdf') return 'pdf';
	if (ext === 'docx' || ct.includes('wordprocessingml')) return 'word';
	if (ext === 'xlsx' || ct.includes('spreadsheetml')) return 'sheet';
	if (ext === 'pptx' || ct.includes('presentationml')) return 'slides';
	return 'file';
}

export function formatBytes(n: number): string {
	if (!n) return '';
	if (n < 1024) return `${n} B`;
	if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10240 ? 1 : 0)} KB`;
	return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

const KIND_LABEL: Record<UploadedKind, string> = {
	image: 'Image',
	pdf: 'PDF',
	word: 'Word document',
	sheet: 'Spreadsheet',
	slides: 'Presentation',
	file: 'File',
};

export function uploadedSubtitle(o: UploadedOutput): string {
	const size = formatBytes(o.size);
	return size ? `${KIND_LABEL[uploadedKind(o)]} · ${size}` : KIND_LABEL[uploadedKind(o)];
}
