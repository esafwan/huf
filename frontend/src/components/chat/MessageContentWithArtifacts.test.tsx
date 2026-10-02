// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { MessageContentWithArtifacts } from './MessageContentWithArtifacts';
import { ArtifactPaneProvider } from './artifacts/ArtifactPaneContext';

vi.mock('sonner', () => ({ toast: { error: vi.fn() } }));
vi.mock('@/lib/frappe-sdk', () => ({ call: { get: vi.fn(), post: vi.fn() }, db: {} }));
vi.mock('@/components/ai-elements/message', () => ({
	MessageResponse: ({ children }: { children: React.ReactNode }) => <div data-testid="text">{children}</div>,
}));
vi.mock('./ArtifactRenderer', () => ({
	ArtifactRenderer: ({ artifact }: { artifact: { type: string } }) => (
		<div data-testid="inline-artifact">{artifact.type}</div>
	),
}));
vi.mock('./JSXPreviewRenderer', () => ({ JSXPreviewRenderer: () => null }));
vi.mock('./WebPreviewRenderer', () => ({ WebPreviewRenderer: () => null }));

afterEach(cleanup);

function renderMsg(content: string, withPane = true) {
	const body = <MessageContentWithArtifacts content={content} messageId="MSG-1" />;
	return render(
		<MemoryRouter>
			{withPane ? (
				<ArtifactPaneProvider
					activeTarget={null}
					durableArtifacts={[]}
					isMobile={false}
					autoOpen
					open={vi.fn()}
					toggle={vi.fn()}
				>
					{body}
				</ArtifactPaneProvider>
			) : (
				body
			)}
		</MemoryRouter>
	);
}

const long = Array.from({ length: 20 }, (_, i) => `line ${i}`).join('\n');

describe('MessageContentWithArtifacts', () => {
	it.each(['document', 'html', 'chart'])('renders a card, not the body, for %s', (type) => {
		renderMsg(`Intro <artifact type="${type}" title="T">body</artifact>`);
		expect(screen.getAllByTestId('artifact-card')).toHaveLength(1);
		expect(screen.queryByTestId('inline-artifact')).toBeNull();
	});

	it('keeps short code inline and long code as a card', () => {
		renderMsg(`<artifact type="code" language="js">const a = 1;</artifact>`);
		expect(screen.getByTestId('inline-artifact')).toBeTruthy();
		cleanup();
		renderMsg(`<artifact type="code" language="js">${long}</artifact>`);
		expect(screen.getByTestId('artifact-card')).toBeTruthy();
	});

	it('leaves fenced code without an artifact tag as plain text', () => {
		renderMsg('```js\nconst a = 1;\n```');
		expect(screen.queryByTestId('artifact-card')).toBeNull();
		expect(screen.getByTestId('text')).toBeTruthy();
	});

	it('shows a placeholder while an artifact tag is still streaming', () => {
		renderMsg('Working <artifact type="html" title="Page"><div>par');
		expect(screen.getByTestId('artifact-streaming-card').textContent).toContain('Page');
		expect(screen.getByTestId('text').textContent).not.toContain('<artifact');
	});

	it('falls back to the inline renderer outside the chat pane context', () => {
		renderMsg('<artifact type="html">x</artifact>', false);
		expect(screen.getByTestId('inline-artifact')).toBeTruthy();
		expect(screen.queryByTestId('artifact-card')).toBeNull();
	});
});
