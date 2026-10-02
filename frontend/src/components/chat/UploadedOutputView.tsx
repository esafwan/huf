/** Pane view for an uploaded desktop output (pointer artifact). */
import { useState } from 'react';
import { DownloadIcon, FileText, FileSpreadsheet, ImageIcon, Presentation, File as FileIcon } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { uploadedKind, uploadedSubtitle, type UploadedKind, type UploadedOutput } from '@/utils/uploadedOutput';

const ICONS: Record<UploadedKind, LucideIcon> = {
	image: ImageIcon,
	pdf: FileText,
	word: FileText,
	sheet: FileSpreadsheet,
	slides: Presentation,
	file: FileIcon,
};

export function uploadedIcon(o: UploadedOutput): LucideIcon {
	return ICONS[uploadedKind(o)];
}

export function UploadedOutputView({ output }: { output: UploadedOutput }) {
	const [failed, setFailed] = useState(false);
	const kind = uploadedKind(output);
	const Icon = uploadedIcon(output);
	const canPreview = !failed && (kind === 'image' || kind === 'pdf');
	return (
		<div data-testid="uploaded-output-view" className="flex flex-col gap-3">
			<div className="flex items-center gap-3">
				<Icon className="size-5 text-steel" />
				<div className="min-w-0 flex-1">
					<div className="truncate text-sm font-medium">{output.filename}</div>
					<div className="text-xs text-steel">{uploadedSubtitle(output)}</div>
				</div>
				<Button asChild size="sm" variant="outline">
					<a href={output.fileUrl} download={output.filename}>
						<DownloadIcon className="size-4" />
						Download
					</a>
				</Button>
			</div>
			{canPreview && kind === 'image' && (
				<img
					src={output.fileUrl}
					alt={output.filename}
					onError={() => setFailed(true)}
					className="max-h-[70vh] max-w-full rounded border object-contain"
				/>
			)}
			{canPreview && kind === 'pdf' && (
				<iframe src={output.fileUrl} title={output.filename} className="h-[70vh] w-full rounded border" />
			)}
			{(failed || (kind !== 'image' && kind !== 'pdf')) && (
				<p data-testid="uploaded-no-preview" className="text-sm text-steel">
					{failed ? 'Preview unavailable.' : 'No inline preview for this file type.'} Use Download to open it.
				</p>
			)}
		</div>
	);
}
