/**
 * One native view per artifact type, shared by the chat inline renderer and
 * the right pane. No Preview/Source toggle and no actions: source access is
 * via the Export menu ("Download source").
 */
import { CodeBlock } from '@/components/ai-elements/code-block';
import { Mermaid } from '@/components/ui/mermaid';
import { JSXPreview, JSXPreviewContent, JSXPreviewExport } from '@/components/ui/jsx-preview';
import { Video } from '@/components/ai-elements/video';
import { DocumentPreview } from '@/components/chat/DocumentPreview';
import { FrappeListView } from '@/components/chat/frappe-views/FrappeListView';
import { FrappeFormView } from '@/components/chat/frappe-views/FrappeFormView';
import { FrappeReportView } from '@/components/chat/frappe-views/FrappeReportView';
import { UploadedOutputView } from '@/components/chat/UploadedOutputView';
import { parseUploadedOutput } from '@/utils/uploadedOutput';
import type { FrappeViewPayload, ParsedArtifact } from '@/types/artifact.types';

/** Ids minted by the client-side parser for transient, unsaved artifacts. */
const TRANSIENT_ARTIFACT_ID = /^artifact-\d+-\d+$/;

/**
 * True when an id refers to a durable, server-owned Artifact row rather than a
 * throwaway id created while parsing message content in the browser. Only
 * durable artifacts can be fetched by name from the server.
 */
export function isDurableArtifactId(id: string | undefined): id is string {
	return Boolean(id) && !TRANSIENT_ARTIFACT_ID.test(id as string);
}

// Map common language aliases to Shiki language names
const LANGUAGE_MAP: Record<string, string> = {
	js: 'javascript',
	ts: 'typescript',
	py: 'python',
	rb: 'ruby',
	yml: 'yaml',
	sh: 'bash',
	shell: 'bash',
	zsh: 'bash',
	dockerfile: 'docker',
	md: 'markdown',
	txt: 'text',
	text: 'text',
};

export function normalizeLanguage(language?: string): string {
	if (!language) return 'text';
	const lower = language.toLowerCase();
	return LANGUAGE_MAP[lower] || lower;
}

/**
 * Parses a frappe-list/frappe-form/frappe-report artifact body (JSON per
 * FrappeViewPayload, emitted by
 * huf/ai/tools/frappe_generic.py::handle_render_frappe_view) and renders the
 * matching view component. Malformed JSON (or a payload missing the fields
 * these views need) falls back to a plain error message rather than
 * throwing, since this runs inside a streaming chat message.
 */
function renderFrappeView(type: 'frappe-list' | 'frappe-form' | 'frappe-report', content: string) {
	let payload: FrappeViewPayload;
	try {
		payload = JSON.parse(content) as FrappeViewPayload;
	} catch (error) {
		console.error('Failed to parse frappe view artifact payload:', error);
		return (
			<div className="text-sm text-destructive p-4">
				Could not parse this Frappe view - invalid JSON.
			</div>
		);
	}

	// Defensive normalization: a model asked to relay the tool's artifact tag
	// "verbatim" can still occasionally paraphrase a key name (observed:
	// gemini-3.6-flash emitting `doc` instead of `data` for mode="form"
	// while otherwise reproducing the payload faithfully). Recover the
	// common single-key-rename case rather than showing a hard error for
	// data that's actually all there.
	if (payload && payload.data === undefined && (payload as unknown as Record<string, unknown>).doc !== undefined) {
		payload = { ...payload, data: (payload as unknown as Record<string, unknown>).doc } as FrappeViewPayload;
	}

	if (!payload || !payload.meta || payload.data === undefined) {
		return (
			<div className="text-sm text-destructive p-4">
				This Frappe view is missing required data (meta/data).
			</div>
		);
	}

	switch (type) {
		case 'frappe-list':
			return <FrappeListView payload={payload} />;
		case 'frappe-form':
			return <FrappeFormView payload={payload} />;
		case 'frappe-report':
			return <FrappeReportView payload={payload} />;
	}
}

export function NativeArtifactView({ artifact }: { artifact: ParsedArtifact }) {
	const uploaded = artifact.type === 'document' || artifact.type === 'image' ? parseUploadedOutput(artifact.content) : null;
	if (uploaded) return <UploadedOutputView output={uploaded} />;
	switch (artifact.type) {
		case 'code':
		case 'react-component':
			return (
				<CodeBlock
					code={artifact.content}
					language={normalizeLanguage(artifact.language)}
					showLineNumbers
				/>
			);

		case 'html':
			return (
				<div className="flex flex-col gap-2">
					<iframe
						srcDoc={artifact.content}
						sandbox=""
						className="w-full h-[70vh] border rounded bg-panel"
						title={artifact.title || 'HTML Preview'}
					/>
				</div>
			);

		case 'svg':
			return (
				<div className="flex flex-col gap-2">
					<iframe
						srcDoc={artifact.content}
						sandbox=""
						className="w-full h-[70vh] bg-panel rounded border"
						title={artifact.title || 'SVG Preview'}
					/>
				</div>
			);

		case 'mermaid':
			return (
				<div className="flex flex-col gap-2">
					<Mermaid chart={artifact.content} />
				</div>
			);

		case 'video': {
			const src = artifact.content.trim();
			return <Video src={src} title={artifact.title} className="max-w-full" />;
		}

		case 'markdown':
		case 'document':
			// A DURABLE (server-owned) artifact is previewed by name via
			// get_artifact_html. In chat, most of these objects come from the
			// client-side parser instead, which mints throwaway ids of the
			// form `artifact-<timestamp>-<index>` (artifactParser.ts) - those
			// match no Artifact row. Rather than falling back to raw
			// <MessageResponse> (which prints an HTML document's <style>
			// block as literal text, see the bug this fixes), render those
			// through preview_document_html by sending the content directly.
			return isDurableArtifactId(artifact.id) ? (
				<DocumentPreview artifactName={artifact.id} />
			) : (
				<DocumentPreview
					content={artifact.content}
					language={artifact.language}
					title={artifact.title}
				/>
			);

		case 'jsx':
		case 'chart':
			return (
				<div className="flex flex-col gap-2">
					<JSXPreview jsx={artifact.content} className="min-h-[300px]">
						<div className="absolute top-2 right-2 z-10">
							<JSXPreviewExport filename={artifact.title?.replace(/[^a-z0-9]/gi, '_') || 'chart'} />
						</div>
						<div className="pt-10">
							<JSXPreviewContent />
						</div>
					</JSXPreview>
				</div>
			);

		case 'frappe-list':
		case 'frappe-form':
		case 'frappe-report':
			return renderFrappeView(artifact.type, artifact.content);

		default:
			return (
				<pre className="whitespace-pre-wrap text-sm font-mono p-4 bg-muted/50 rounded">
					{artifact.content}
				</pre>
			);
	}
}

export default NativeArtifactView;
