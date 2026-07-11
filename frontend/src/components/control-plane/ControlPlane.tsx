'use client';
import { TopBar } from './TopBar';
import { Rail } from './Rail';
import { ControlPlaneChat } from './ControlPlaneChat';
import { ContextSidebar } from './ContextSidebar';

export function ControlPlane() {
  return (
    <div className="flex h-screen flex-col">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <Rail />
        {/* left artifact panel column is added in P8.1 (URL-param driven) */}
        <ControlPlaneChat />
        <ContextSidebar />
      </div>
    </div>
  );
}
