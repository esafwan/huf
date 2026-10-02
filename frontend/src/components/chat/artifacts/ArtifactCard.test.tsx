// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { ArtifactCard, ArtifactStreamingCard } from './ArtifactCard';
import { ArtifactPaneProvider } from './ArtifactPaneContext';
import type { ArtifactPaneTarget } from '@/components/chat/useArtifactPane';
import type { ArtifactListItem } from '@/services/artifactPanelApi';
import type { ParsedArtifact } from '@/types/artifact.types';

vi.mock('sonner', () => ({ toast: { error: vi.fn() } }));
vi.mock('@/lib/frappe-sdk', () => ({ call: { get: vi.fn(), post: vi.fn() }, db: {} }));
const navigateMock = vi.fn();
vi.mock('react-router-dom', async (orig) => ({
	...(await orig<typeof import('react-router-dom')>()),
	useNavigate: () => navigateMock,
}));

afterEach(() => {
	cleanup();
	navigateMock.mockReset();
});

const artifact: ParsedArtifact = { id: 'artifact-1-0', type: 'html', title: 'Landing', content: '<p>hi</p>' };
const rows: ArtifactListItem[] = [
	{ name: 'ART-9', message: 'MSG-1', message_index: 0, artifact_type: 'html', size_bytes: 9, creation: '' },
];

function setup(opts: { active?: ArtifactPaneTarget | null; isMobile?: boolean; live?: boolean; autoOpen?: boolean } = {}) {
	const open = vi.fn();
	const toggle = vi.fn();
	render(
		<MemoryRouter>
			<ArtifactPaneProvider
				activeTarget={opts.active ?? null}
				durableArtifacts={rows}
				isMobile={opts.isMobile ?? false}
				autoOpen={opts.autoOpen ?? true}
				open={open}
				toggle={toggle}
			>
				<ArtifactCard artifact={artifact} messageId="MSG-1" ordinal={0} indexInMessage={0} />
			</ArtifactPaneProvider>
		</MemoryRouter>
	);
	return { open, toggle };
}

describe('ArtifactCard', () => {
	it('renders title and subtitle but not the artifact body', () => {
		setup();
		expect(screen.getByText('Landing')).toBeTruthy();
		expect(screen.getByText(/HTML page/)).toBeTruthy();
		expect(document.querySelector('iframe')).toBeNull();
		expect(screen.getByRole('button', { name: 'Open' })).toBeTruthy();
	});

	it('toggles the pane through context on Open', async () => {
		const { toggle } = setup();
		await userEvent.click(screen.getByRole('button', { name: 'Open' }));
		expect(toggle).toHaveBeenCalledTimes(1);
		const target = toggle.mock.calls[0][0];
		expect(target).toMatchObject({ kind: 'parsed', key: 'MSG-1:0', durableName: 'ART-9' });
	});

	it('shows Hide when its durable row is the active pane target', () => {
		setup({ active: { kind: 'durable', name: 'ART-9', artifact_type: 'html' } });
		expect(screen.getByRole('button', { name: 'Hide' })).toBeTruthy();
	});

	it('navigates to /artifact/:name on mobile instead of opening the pane', async () => {
		const { toggle } = setup({ isMobile: true });
		await userEvent.click(screen.getByRole('button', { name: 'Open' }));
		expect(toggle).not.toHaveBeenCalled();
		expect(navigateMock).toHaveBeenCalledWith('/artifact/ART-9');
	});

	it('does not auto-open on mount without a live streaming signal (history load)', () => {
		const { open } = setup();
		expect(open).not.toHaveBeenCalled();
	});

	it('auto-opens once when it arrives live after a streaming placeholder', () => {
		const open = vi.fn();
		render(
			<MemoryRouter>
				<ArtifactPaneProvider
					activeTarget={null}
					durableArtifacts={rows}
					isMobile={false}
					autoOpen
					open={open}
					toggle={vi.fn()}
				>
					<ArtifactStreamingCard type="html" />
					<ArtifactCard artifact={artifact} messageId="MSG-1" ordinal={0} indexInMessage={0} />
				</ArtifactPaneProvider>
			</MemoryRouter>
		);
		expect(open).toHaveBeenCalledTimes(1);
	});
});
