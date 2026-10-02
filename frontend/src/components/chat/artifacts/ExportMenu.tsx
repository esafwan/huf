/**
 * Export menu for an artifact. All downloads live here (no separate Download
 * button). Server conversions (PDF/DOCX/HTML) need a durable Artifact row;
 * "Download source" is a client Blob of the artifact body.
 */
import { useState } from 'react';
import { DownloadIcon } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { exportArtifact } from '@/services/artifactApi';
import { parseUploadedOutput } from '@/utils/uploadedOutput';
import { downloadSource, exportOptionsFor, type ExportOption } from '@/utils/artifactExport';

export interface ExportMenuProps {
	artifact: { type: string; title?: string; language?: string; content: string };
	/** Durable Artifact name; required for PDF/DOCX/HTML conversions. */
	durableName?: string;
	className?: string;
}

export function ExportMenu({ artifact, durableName, className }: ExportMenuProps) {
	const [busy, setBusy] = useState(false);
	const options = exportOptionsFor(artifact.type, artifact.content);
	if (options.length === 0) return null;

	const run = async (option: ExportOption) => {
		if (option.id === 'file') {
			const up = parseUploadedOutput(artifact.content);
			if (up) window.open(up.fileUrl, '_blank', 'noopener');
			return;
		}
		if (option.id === 'source') {
			downloadSource(artifact);
			return;
		}
		if (!durableName) return;
		setBusy(true);
		try {
			const result = await exportArtifact(durableName, option.id);
			if (result?.file_url) window.open(result.file_url, '_blank', 'noopener');
		} catch {
			toast.error(`Could not export as ${option.label}`);
		} finally {
			setBusy(false);
		}
	};

	return (
		<DropdownMenu>
			<DropdownMenuTrigger asChild>
				<Button
					type="button"
					variant="ghost"
					size="sm"
					aria-label="Export"
					disabled={busy}
					className={className}
				>
					<DownloadIcon className="size-4" />
					<span className="text-[12px]">Export</span>
				</Button>
			</DropdownMenuTrigger>
			<DropdownMenuContent align="end">
				{options.map((option) => (
					<DropdownMenuItem
						key={option.id}
						disabled={option.id !== 'source' && option.id !== 'file' && !durableName}
						onSelect={() => void run(option)}
					>
						{option.label}
					</DropdownMenuItem>
				))}
			</DropdownMenuContent>
		</DropdownMenu>
	);
}

export default ExportMenu;
