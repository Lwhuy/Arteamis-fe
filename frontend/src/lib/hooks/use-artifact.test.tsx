import { describe, it, expect, vi } from 'vitest';
import { renderHook } from '@testing-library/react';

const push = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams('artifact=source&aid=abc&loc=4'),
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
});
