// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render } from '@testing-library/react';
import { NativeArtifactView } from './NativeArtifactView';
import { UploadedOutputView } from './UploadedOutputView';

afterEach(cleanup);

describe('user-controlled HTML is sandboxed', () => {
	it.each(['html', 'svg'] as const)('%s artifact iframe has an empty sandbox', (type) => {
		const { container } = render(
			<NativeArtifactView artifact={{ id: 'a-1-0', type, title: 't', content: '<script>1</script>' }} />,
		);
		const frame = container.querySelector('iframe');
		expect(frame).not.toBeNull();
		expect(frame!.getAttribute('sandbox')).toBe('');
		expect(frame!.getAttribute('sandbox')).not.toContain('allow-same-origin');
	});
	it('pdf viewer iframe uses the validated same-origin path', () => {
		const { container } = render(
			<UploadedOutputView output={{ fileUrl: '/private/files/a.pdf', filename: 'a.pdf', contentType: 'application/pdf', size: 1 }} />,
		);
		expect(container.querySelector('iframe')!.getAttribute('src')).toBe('/private/files/a.pdf');
	});
});
