/**
 * Helper component that parses and renders message content with artifacts, web previews, and JSX previews.
 * Extracts <artifact>, <web-preview>, and <jsx-preview> tags from content and renders them as components.
 * Artifact-class outputs (see utils/artifactClass.ts) render as compact cards; their body lives in the right pane.
 */

import { MessageResponse } from '@/components/ai-elements/message';
import { ArtifactRenderer } from './ArtifactRenderer';
import { ArtifactCard, ArtifactStreamingCard } from './artifacts/ArtifactCard';
import { useArtifactPaneContext } from './artifacts/ArtifactPaneContext';
import { WebPreviewRenderer } from './WebPreviewRenderer';
import { JSXPreviewRenderer } from './JSXPreviewRenderer';
import { hasArtifacts } from '@/utils/artifactParser';
import { hasWebPreviews } from '@/utils/webPreviewParser';
import { hasJSXPreviews } from '@/utils/jsxPreviewParser';
import { parseMessagePreviewContent, unwrapJsonWrappedAnswer } from '@/utils/messageContentParser';
import { decodeHtmlEntities } from '@/utils/decodeHtmlEntities';
import { isCardArtifact } from '@/utils/artifactClass';
import { artifactOrdinals } from '@/utils/artifactIdentity';
import { splitStreamingArtifact } from '@/utils/streamingArtifact';

interface MessageContentWithArtifactsProps {
	content: string;
	/** Agent Message document name for preview links */
	messageId: string;
}

export function MessageContentWithArtifacts({ content, messageId }: MessageContentWithArtifactsProps) {
	const paneCtx = useArtifactPaneContext();
	const fullDecoded = unwrapJsonWrappedAnswer(decodeHtmlEntities(content));
	const streaming = splitStreamingArtifact(fullDecoded);
	const decodedContent = streaming ? streaming.text : fullDecoded;

	const contentHasArtifacts = hasArtifacts(decodedContent);
	const contentHasWebPreviews = hasWebPreviews(decodedContent);
	const contentHasJSXPreviews = hasJSXPreviews(decodedContent);

	if (!contentHasArtifacts && !contentHasWebPreviews && !contentHasJSXPreviews) {
		return (
			<>
				{decodedContent.trim() && (
					<div className="min-w-0 max-w-full overflow-x-auto">
						<MessageResponse>{decodedContent}</MessageResponse>
					</div>
				)}
				{streaming && <ArtifactStreamingCard type={streaming.type} title={streaming.title} />}
			</>
		);
	}

	const parsed = parseMessagePreviewContent(decodedContent);
	const { textContent, jsxPreviews, webPreviews, artifacts } = parsed;
	const ordinals = artifactOrdinals(decodedContent);

	return (
		<>
			{textContent && textContent.trim() && (
				<div className="min-w-0 max-w-full overflow-x-auto">
					<MessageResponse>{textContent}</MessageResponse>
				</div>
			)}

			{jsxPreviews.map((preview, idx) => (
				<JSXPreviewRenderer
					key={`${messageId}-jsx-${idx}`}
					preview={preview}
					messageId={messageId}
					previewContent={parsed}
				/>
			))}

			{webPreviews.map((preview, idx) => (
				<WebPreviewRenderer key={`${messageId}-preview-${idx}`} preview={preview} />
			))}

			{artifacts.map((artifact, idx) =>
				paneCtx && isCardArtifact(artifact) ? (
					<ArtifactCard
						key={`${messageId}-artifact-${idx}`}
						artifact={artifact}
						messageId={messageId}
						ordinal={ordinals[idx] ?? -1}
						indexInMessage={idx}
					/>
				) : (
					<ArtifactRenderer
						key={`${messageId}-artifact-${idx}`}
						artifact={artifact}
						messageId={messageId}
						previewContent={parsed}
					/>
				)
			)}

			{streaming && <ArtifactStreamingCard type={streaming.type} title={streaming.title} />}
		</>
	);
}
