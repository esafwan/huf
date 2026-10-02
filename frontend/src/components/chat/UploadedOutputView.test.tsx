// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup } from '@testing-library/react';
afterEach(cleanup);
// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
// @vitest-environment jsdom
import { UploadedOutputView } from './UploadedOutputView';
// @vitest-environment jsdom

// @vitest-environment jsdom
const base = { fileUrl: '/private/files/a', filename: 'a', contentType: '', size: 10 };
// @vitest-environment jsdom

// @vitest-environment jsdom
describe('UploadedOutputView', () => {
// @vitest-environment jsdom
	it('previews images and links download', () => {
// @vitest-environment jsdom
		render(<UploadedOutputView output={{ ...base, filename: 'a.png', contentType: 'image/png' }} />);
// @vitest-environment jsdom
		expect(screen.getByRole('img')).toHaveAttribute('src', '/private/files/a');
// @vitest-environment jsdom
		expect(screen.getByRole('link', { name: /download/i })).toHaveAttribute('href', '/private/files/a');
// @vitest-environment jsdom
	});
// @vitest-environment jsdom
	it('falls back when image fails', () => {
// @vitest-environment jsdom
		render(<UploadedOutputView output={{ ...base, filename: 'a.png', contentType: 'image/png' }} />);
// @vitest-environment jsdom
		fireEvent.error(screen.getByRole('img'));
// @vitest-environment jsdom
		expect(screen.getByTestId('uploaded-no-preview')).toHaveTextContent('Preview unavailable');
// @vitest-environment jsdom
	});
// @vitest-environment jsdom
	it('embeds pdf', () => {
// @vitest-environment jsdom
		render(<UploadedOutputView output={{ ...base, filename: 'a.pdf', contentType: 'application/pdf' }} />);
// @vitest-environment jsdom
		expect(screen.getByTitle('a.pdf')).toBeTruthy();
// @vitest-environment jsdom
	});
// @vitest-environment jsdom
	it('no preview for office files', () => {
// @vitest-environment jsdom
		render(<UploadedOutputView output={{ ...base, filename: 'a.docx' }} />);
// @vitest-environment jsdom
		expect(screen.getByTestId('uploaded-no-preview')).toBeTruthy();
// @vitest-environment jsdom
	});
// @vitest-environment jsdom
});
