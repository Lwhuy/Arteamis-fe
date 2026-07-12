import { describe, it, expect, vi } from 'vitest';
import { renderHook } from '@testing-library/react';

const push = vi.fn();
let currentSearch = 'artifact=source&aid=abc&loc=4';
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(currentSearch),
}));

import { useArtifact } from './use-artifact';

describe('useArtifact', () => {
  it('parses artifact params from the URL', () => {
    const { result } = renderHook(() => useArtifact());
    expect(result.current.artifact).toEqual({ type: 'source', id: 'abc', loc: '4' });
  });

  it('openArtifact pushes the encoded params', () => {
    const { result } = renderHook(() => useArtifact());
    result.current.openArtifact('belief', 'xyz');
    expect(push).toHaveBeenCalled();
    expect(push.mock.calls[0][0]).toContain('artifact=belief');
    expect(push.mock.calls[0][0]).toContain('aid=xyz');
  });

  it('openArtifact carries an optional q highlight param', () => {
    const { result } = renderHook(() => useArtifact());
    result.current.openArtifact('source', 'xyz', undefined, 'SMB skews higher');
    expect(push.mock.calls[push.mock.calls.length - 1][0]).toContain('q=SMB');
  });

  it('openArtifact omits q when not provided', () => {
    const { result } = renderHook(() => useArtifact());
    result.current.openArtifact('source', 'xyz');
    expect(push.mock.calls[push.mock.calls.length - 1][0]).not.toContain('q=');
  });
});

describe('useArtifact with a q param present in the URL', () => {
  it('parses q from the URL into the artifact ref', () => {
    currentSearch = 'artifact=source&aid=abc&loc=4&q=SMB%20skews%20higher';
    const { result } = renderHook(() => useArtifact());
    expect(result.current.artifact).toEqual({ type: 'source', id: 'abc', loc: '4', q: 'SMB skews higher' });
    currentSearch = 'artifact=source&aid=abc&loc=4';
  });
});
