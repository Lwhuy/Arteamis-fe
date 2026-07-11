'use client';
import { useRouter, usePathname, useSearchParams } from 'next/navigation';

export type ArtifactRef = { type: 'source' | 'belief'; id: string; loc?: string };

export function useArtifact() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const type = params.get('artifact');
  const id = params.get('aid');
  const artifact: ArtifactRef | null =
    (type === 'source' || type === 'belief') && id
      ? { type, id, loc: params.get('loc') ?? undefined }
      : null;

  const write = (next: URLSearchParams) => router.push(`${pathname}?${next.toString()}`, { scroll: false });

  const openArtifact = (t: ArtifactRef['type'], aid: string, loc?: string) => {
    const next = new URLSearchParams(params.toString());
    next.set('artifact', t);
    next.set('aid', aid);
    if (loc) next.set('loc', loc); else next.delete('loc');
    write(next);
  };
  const closeArtifact = () => {
    const next = new URLSearchParams(params.toString());
    next.delete('artifact'); next.delete('aid'); next.delete('loc');
    write(next);
  };

  return { artifact, openArtifact, closeArtifact };
}
