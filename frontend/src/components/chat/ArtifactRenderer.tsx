/**
 * Renderer component for AI-generated artifacts.
 *
 * This component takes a parsed artifact and renders it using the appropriate
 * visualization based on its type (code, html, svg, mermaid, etc.)
 */

import { useState, useCallback } from 'react';
import {
	Artifact,
	ArtifactHeader,
	ArtifactTitle,
	ArtifactDescription,
	ArtifactActions,
	ArtifactAction,
	ArtifactContent,
	ArtifactClose,
} from '@/components/ai-elements/artifact';
import { CodeBlock } from '@/components/ai-elements/code-block';
import { NativeArtifactView, normalizeLanguage, isDurableArtifactId } from '@/components/chat/NativeArtifactView';
import { ExportMenu } from '@/components/chat/artifacts/ExportMenu';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
	CopyIcon,
	MaximizeIcon,
	MinimizeIcon,
	CheckIcon,
	CodeIcon,
	FileTextIcon,
	ImageIcon,
	LayoutIcon,
	BarChartIcon,
	ExternalLinkIcon,
	VideoIcon,
} from 'lucide-react';
import type { ParsedArtifact, ArtifactType } from '@/types/artifact.types';
import type { ParsedMessageContent } from '@/utils/messageContentParser';
import { writePreviewCache } from '@/utils/previewCache';
import { cn } from '@/lib/utils';
import { TableIcon } from 'lucide-react';

interface ArtifactRendererProps {
	artifact: ParsedArtifact;
	onClose?: () => void;
	className?: string;
	/** Agent Message document name — enables "Open" for jsx/chart artifacts */
	messageId?: string;
	/** Parsed message content for same-session full-screen preview */
	previewContent?: ParsedMessageContent;
}

// Map artifact types to icons
const ARTIFACT_ICONS: Record<ArtifactType, typeof CodeIcon> = {
	code: CodeIcon,
	document: FileTextIcon,
	html: LayoutIcon,
	svg: ImageIcon,
	mermaid: LayoutIcon,
	'react-component': CodeIcon,
	markdown: FileTextIcon,
	jsx: LayoutIcon,
	chart: BarChartIcon,
	video: VideoIcon,
	'frappe-list': TableIcon,
	'frappe-form': FileTextIcon,
	'frappe-report': TableIcon,
};

export function ArtifactRenderer({
	artifact,
	onClose,
	className,
	messageId,
	previewContent,
}: ArtifactRendererProps) {
	const [isFullscreen, setIsFullscreen] = useState(false);
	const [isCopied, setIsCopied] = useState(false);
	const [view, setView] = useState<'preview' | 'source'>('preview');

	const handleCopy = useCallback(async () => {
		try {
			await navigator.clipboard.writeText(artifact.content);
			setIsCopied(true);
			setTimeout(() => setIsCopied(false), 2000);
		} catch (error) {
			console.error('Failed to copy:', error);
		}
	}, [artifact.content]);

	const toggleFullscreen = useCallback(() => {
		setIsFullscreen((prev) => !prev);
	}, []);

	const handleOpenPreview = useCallback(() => {
		if (!messageId) return;
		if (previewContent) {
			writePreviewCache(messageId, previewContent);
		} else if (artifact.type === 'jsx' || artifact.type === 'chart') {
			writePreviewCache(messageId, {
				textContent: '',
				jsxPreviews: [],
				webPreviews: [],
				artifacts: [artifact],
			});
		}
		window.open(`/huf/view/${messageId}`, '_blank', 'noopener');
	}, [messageId, previewContent, artifact]);

	const renderContent = () =>
		view === 'source' ? (
			<CodeBlock
				code={artifact.content}
				language={normalizeLanguage(artifact.language)}
				showLineNumbers
			/>
		) : (
			<NativeArtifactView artifact={artifact} />
		);

	const Icon = ARTIFACT_ICONS[artifact.type] || CodeIcon;

	return (
		<Artifact
			className={cn(
				'my-4',
				isFullscreen && 'fixed inset-4 z-50 shadow-2xl',
				className
			)}
		>
			<ArtifactHeader>
				<div className="flex items-center gap-2 min-w-0 flex-1">
					<Icon className="size-4 shrink-0 text-muted-foreground" />
					<div className="min-w-0 flex-1">
						<ArtifactTitle className="truncate">
							{artifact.title || `${artifact.type} artifact`}
						</ArtifactTitle>
						{artifact.language && (
							<ArtifactDescription className="truncate">
								{artifact.language}
							</ArtifactDescription>
						)}
					</div>
				</div>
				<ArtifactActions>
					<Tabs
						value={view}
						onValueChange={(value) => setView(value as 'preview' | 'source')}
					>
						<TabsList variant="pill" size="compact">
							<TabsTrigger value="preview">Preview</TabsTrigger>
							<TabsTrigger value="source">Source</TabsTrigger>
						</TabsList>
					</Tabs>
					{messageId && (artifact.type === 'jsx' || artifact.type === 'chart') && (
						<ArtifactAction
							icon={ExternalLinkIcon}
							tooltip="Open full screen"
							label="Open in new tab"
							onClick={handleOpenPreview}
						/>
					)}
					<ArtifactAction
						icon={isCopied ? CheckIcon : CopyIcon}
						tooltip={isCopied ? 'Copied!' : 'Copy'}
						label="Copy content"
						onClick={handleCopy}
					/>
					<ExportMenu
						artifact={artifact}
						durableName={isDurableArtifactId(artifact.id) ? artifact.id : undefined}
					/>
					<ArtifactAction
						icon={isFullscreen ? MinimizeIcon : MaximizeIcon}
						tooltip={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
						label={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
						onClick={toggleFullscreen}
					/>
					{onClose && <ArtifactClose onClick={onClose} />}
				</ArtifactActions>
			</ArtifactHeader>
			<ArtifactContent className={isFullscreen ? 'flex-1' : ''}>
				{renderContent()}
			</ArtifactContent>
		</Artifact>
	);
}

export default ArtifactRenderer;
