"use client";

import { useState } from "react";
import { ManagedLaunchSection } from "./managed-launch-section";
import { TelemetrySection } from "./telemetry-section";
import { NodeCoverageSection } from "./node-coverage-section";
import { MediaRecoverySection } from "./media-recovery-section";

export function ObservationSection({ projectId }: { projectId: number | null }) {
  const [, setExecution] = useState("");

  if (projectId == null) {
    return <p className="text-xs text-white/50">Выберите проект в студии для наблюдения.</p>;
  }

  return (
    <section data-testid="observation-panel" className="space-y-3 text-xs text-white/80">
      <ManagedLaunchSection
        projectId={projectId}
        context={null}
        actions={null}
        diagnosis={null}
        onExecution={(id) => setExecution(id)}
      />
      <TelemetrySection projectId={projectId} />
      <NodeCoverageSection projectId={projectId} />
      <MediaRecoverySection projectId={projectId} />
    </section>
  );
}
