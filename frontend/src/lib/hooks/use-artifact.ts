'use client';
import { useRouter, usePathname, useSearchParams } from 'next/navigation';

export type ArtifactRef = { type: 'source' | 'belief'; id: string; loc?: string; q?: string };

export function useArtifact() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const type = params.get('artifact');
  const id = params.get('aid');
  const artifact: ArtifactRef | null =
    (type === 'source' || type === 'belief') && id
      ? { type, id, loc: params.get('loc') ?? undefined, q: params.get('q') ?? undefined }
      : null;

  const write = (next: URLSearchParams) => router.push(`${pathname}?${next.toString()}`, { scroll: false });

  const openArtifact = (t: ArtifactRef['type'], aid: string, loc?: string, q?: string) => {
    const next = new URLSearchParams(params.toString());
    next.set('artifact', t);
    next.set('aid', aid);
    if (loc) next.set('loc', loc); else next.delete('loc');
    if (q) next.set('q', q); else next.delete('q');
    write(next);
  };
  const closeArtifact = () => {
    const next = new URLSearchParams(params.toString());
    next.delete('artifact'); next.delete('aid'); next.delete('loc'); next.delete('q');
    write(next);
  };

  return { artifact, openArtifact, closeArtifact };
}
