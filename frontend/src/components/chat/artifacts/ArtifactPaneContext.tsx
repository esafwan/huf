/**
 * Lets artifact cards deep in the message tree open/hide the right pane
 * without threading props through ChatWindow -> MessageList -> ChatMessage.
 * Absent outside the chat page (e.g. Hub), where cards fall back to the
 * inline renderer.
 */
import { createContext, useContext, useMemo, useRef, type ReactNode } from 'react';
import type { ArtifactListItem } from '@/services/artifactPanelApi';
import type { ArtifactPaneTarget } from '@/components/chat/useArtifactPane';

export interface ArtifactPaneContextValue {
	activeTarget: ArtifactPaneTarget | null;
	durableArtifacts: ArtifactListItem[];
	isMobile: boolean;
	autoOpen: boolean;
	open: (target: ArtifactPaneTarget) => void;
	toggle: (target: ArtifactPaneTarget) => void;
	/** A streaming placeholder was shown: the next artifact card to mount arrived live. */
	markLive: () => void;
	/** Returns and clears the live flag. */
	consumeLive: () => boolean;
}

const ArtifactPaneContext = createContext<ArtifactPaneContextValue | null>(null);

export function useArtifactPaneContext(): ArtifactPaneContextValue | null {
	return useContext(ArtifactPaneContext);
}

export interface ArtifactPaneProviderProps {
	activeTarget: ArtifactPaneTarget | null;
	durableArtifacts: ArtifactListItem[];
	isMobile: boolean;
	autoOpen: boolean;
	open: (target: ArtifactPaneTarget) => void;
	toggle: (target: ArtifactPaneTarget) => void;
	children: ReactNode;
}

export function ArtifactPaneProvider({
	activeTarget,
	durableArtifacts,
	isMobile,
	autoOpen,
	open,
	toggle,
	children,
}: ArtifactPaneProviderProps) {
	const liveRef = useRef(false);
	const value = useMemo<ArtifactPaneContextValue>(
		() => ({
			activeTarget,
			durableArtifacts,
			isMobile,
			autoOpen,
			open,
			toggle,
			markLive: () => {
				liveRef.current = true;
			},
			consumeLive: () => {
				const was = liveRef.current;
				liveRef.current = false;
				return was;
			},
		}),
		[activeTarget, durableArtifacts, isMobile, autoOpen, open, toggle]
	);
	return <ArtifactPaneContext.Provider value={value}>{children}</ArtifactPaneContext.Provider>;
}
