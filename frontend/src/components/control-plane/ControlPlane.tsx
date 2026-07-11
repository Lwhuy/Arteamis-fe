'use client';
import { TopBar } from './TopBar';
import { Rail } from './Rail';
import { ArtifactReader } from './ArtifactReader';
import { ControlPlaneChat } from './ControlPlaneChat';
import { ContextSidebar } from './ContextSidebar';

export function ControlPlane() {
  return (
    <div className="flex h-screen flex-col">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <Rail />
        <ArtifactReader />
        <ControlPlaneChat />
        <ContextSidebar />
      </div>
    </div>
  );
}
