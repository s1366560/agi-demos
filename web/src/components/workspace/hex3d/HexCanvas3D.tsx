import { forwardRef, useEffect, useId, useImperativeHandle, useRef, useMemo, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import { Vector3 } from 'three';
import { HexScene } from './HexScene';
import { HexInstances } from './HexInstances';
import { AgentMesh } from './AgentMesh';
import { CorridorMesh } from './CorridorMesh';
import { useHex3DPick } from './useHex3DPick';
import { generateGrid, hexToPixel } from '@/components/workspace/hex/useHexLayout';
import type { WorkspaceAgent, TopologyNode, TopologyEdge, CyberObjective } from '@/types/workspace';

export interface HexCanvas3DProps {
  agents: WorkspaceAgent[];
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  objectives?: CyberObjective[];
  onSelectHex?: (q: number, r: number) => void;
  onMoveAgent?: (agentId: string, q: number, r: number) => void;
  onContextMenu?: (q: number, r: number, e: MouseEvent) => void;
  onZoomToAgent?: (agentId: string) => void;
  gridRadius?: number;
  hexSize?: number;
}

export interface HexCanvas3DRef {
  zoomToAgent: (agentId: string) => void;
}

function CameraAnimator({ targetPosition }: { targetPosition: Vector3 | null }) {
  const controls = useRef<any>(null);

  useFrame((_state, delta) => {
    if (targetPosition && controls.current) {
      controls.current.target.lerp(targetPosition, delta * 4);
      controls.current.update();
    }
  });

  return (
    <OrbitControls
      ref={controls}
      minDistance={5}
      maxDistance={40}
      maxPolarAngle={Math.PI / 2.2}
      enableDamping
      makeDefault
    />
  );
}

export const HexCanvas3D = forwardRef<HexCanvas3DRef, HexCanvas3DProps>(
  (
    {
      agents,
      nodes: topologyNodes,
      edges,
      onSelectHex,
      onContextMenu,
      gridRadius = 6,
      hexSize = 1.5,
    },
    ref
  ) => {
    const [zoomTarget, setZoomTarget] = useState<Vector3 | null>(null);

    // Workaround for React StrictMode + R3F: StrictMode double-mounts in dev,
    // which causes the WebGL context to be lost on the second mount because the
    // first mount's context was destroyed during the unmount phase. We defer
    // Canvas rendering by one frame so the previous context cleanup completes.
    const [canvasReady, setCanvasReady] = useState(false);
    const canvasKey = useId();
    useEffect(() => {
      const id = requestAnimationFrame(() => { setCanvasReady(true); });
      return () => { cancelAnimationFrame(id); setCanvasReady(false); };
    }, []);

    const pickOptions = useMemo(() => {
      const opts: {
        onSelectHex?: (q: number, r: number) => void;
        onContextMenu?: (q: number, r: number, e: MouseEvent) => void;
      } = {};
      if (onSelectHex) opts.onSelectHex = onSelectHex;
      if (onContextMenu) opts.onContextMenu = onContextMenu;
      return opts;
    }, [onSelectHex, onContextMenu]);

    const { selectedHex, hoveredHex, handleHexClick, handleHexHover, handleHexContextMenu } = useHex3DPick(pickOptions);

    const gridNodes = useMemo(() => generateGrid(gridRadius), [gridRadius]);

    useImperativeHandle(ref, () => ({
      zoomToAgent: (agentId: string) => {
        const agent = agents.find((a) => a.agent_id === agentId);
        if (agent && agent.hex_q !== undefined && agent.hex_r !== undefined) {
          const { x, y: z } = hexToPixel(agent.hex_q, agent.hex_r, hexSize);
          setZoomTarget(new Vector3(x, 0, z));
        }
      },
    }));

    return (
      <div className="h-full w-full bg-slate-50 relative overflow-hidden cursor-crosshair">
        {canvasReady ? (
          <Canvas key={canvasKey} camera={{ position: [0, 12, 12], fov: 50 }}>
            <HexScene>
              <HexInstances
                nodes={gridNodes}
                hexSize={hexSize}
                agents={agents}
                topologyNodes={topologyNodes}
                selectedHex={selectedHex}
                hoveredHex={hoveredHex}
                onHexClick={handleHexClick}
                onHexHover={handleHexHover}
                onHexContextMenu={handleHexContextMenu}
              />
              {agents.map((agent) => (
                <AgentMesh
                  key={agent.agent_id}
                  agent={agent}
                  hexSize={hexSize}
                  isSelected={
                    selectedHex?.q === agent.hex_q && selectedHex?.r === agent.hex_r
                  }
                />
              ))}
              {edges.map((edge) => (
                <CorridorMesh key={edge.id} edge={edge} hexSize={hexSize} />
              ))}
            </HexScene>
            <CameraAnimator targetPosition={zoomTarget} />
          </Canvas>
        ) : (
          <div className="flex items-center justify-center h-full text-slate-400">
            Initializing 3D view...
          </div>
        )}
      </div>
    );
  }
);

HexCanvas3D.displayName = 'HexCanvas3D';
