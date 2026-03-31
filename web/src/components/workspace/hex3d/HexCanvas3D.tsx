import {
  forwardRef,
  useEffect,
  useId,
  useImperativeHandle,
  useRef,
  useMemo,
  useState,
  useCallback,
} from 'react';
import type { ComponentRef } from 'react';

import { OrbitControls } from '@react-three/drei';
import { Canvas, useFrame } from '@react-three/fiber';
import { Vector3, DoubleSide } from 'three';

import { generateGrid, hexToPixel } from '@/components/workspace/hex/useHexLayout';

import { AgentMesh } from './AgentMesh';
import { CorridorMesh } from './CorridorMesh';
import { HexInstances } from './HexInstances';
import { HexScene } from './HexScene';
import { MessageFlowParticles, type MessageFlowParticlesRef } from './MessageFlowParticles';
import { useHex3DPick } from './useHex3DPick';

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
  triggerMessageFlow: (fromAgentId: string, toAgentId: string) => void;
  selectedAgentId?: string | null;
}

function CameraAnimator({ targetPosition }: { targetPosition: Vector3 | null }) {
  const controls = useRef<ComponentRef<typeof OrbitControls>>(null);

  useFrame((_state, delta) => {
    if (targetPosition && controls.current) {
      const dist = controls.current.target.distanceTo(targetPosition);
      if (dist > 0.01) {
        const lerpFactor = Math.max(2, Math.min(10, 20 / dist));
        controls.current.target.lerp(targetPosition, delta * lerpFactor);
        controls.current.update();
      }
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
    const particlesRef = useRef<MessageFlowParticlesRef>(null);

    // Workaround for React StrictMode + R3F: StrictMode double-mounts in dev,
    // which causes the WebGL context to be lost on the second mount because the
    // first mount's context was destroyed during the unmount phase. We defer
    // Canvas rendering by one frame so the previous context cleanup completes.
    const [canvasReady, setCanvasReady] = useState(false);
    const canvasKey = useId();
    useEffect(() => {
      const id = requestAnimationFrame(() => {
        setCanvasReady(true);
      });
      return () => {
        cancelAnimationFrame(id);
        setCanvasReady(false);
      };
    }, []);

    const pickOptions = useMemo(() => {
      const opts: {
        onSelectHex?: (q: number, r: number) => void;
        onContextMenu?: (q: number, r: number, e: MouseEvent) => void;
        agents?: WorkspaceAgent[];
      } = { agents };
      if (onSelectHex) opts.onSelectHex = onSelectHex;
      if (onContextMenu) opts.onContextMenu = onContextMenu;
      return opts;
    }, [onSelectHex, onContextMenu, agents]);

    const {
      selectedHex,
      hoveredHex,
      selectedAgentId,
      setSelectedAgentId,
      handleHexClick,
      handleHexHover,
      handleHexContextMenu,
    } = useHex3DPick(pickOptions);

    const onHexClick = useCallback(
      (q: number, r: number) => {
        handleHexClick(q, r);
        const agentOnHex = agents.find((a) => a.hex_q === q && a.hex_r === r);
        if (agentOnHex) {
          setSelectedAgentId(agentOnHex.agent_id);
          const { x, y: z } = hexToPixel(q, r, hexSize);
          setZoomTarget(new Vector3(x, 0, z));
        } else {
          setSelectedAgentId(null);
        }
      },
      [handleHexClick, agents, hexSize, setSelectedAgentId]
    );

    const gridNodes = useMemo(() => generateGrid(gridRadius), [gridRadius]);

    useImperativeHandle(
      ref,
      () => ({
        zoomToAgent: (agentId: string) => {
          const agent = agents.find((a) => a.agent_id === agentId);
          if (agent && agent.hex_q !== undefined && agent.hex_r !== undefined) {
            const { x, y: z } = hexToPixel(agent.hex_q, agent.hex_r, hexSize);
            setZoomTarget(new Vector3(x, 0, z));
            setSelectedAgentId(agentId);
          }
        },
        triggerMessageFlow: (fromAgentId: string, toAgentId: string) => {
          particlesRef.current?.triggerFlow(fromAgentId, toAgentId);
        },
        get selectedAgentId() {
          return selectedAgentId;
        },
      }),
      [agents, hexSize, selectedAgentId, setSelectedAgentId]
    );

    const hoveredAgent = useMemo(() => {
      if (!hoveredHex) return null;
      return agents.find((a) => a.hex_q === hoveredHex.q && a.hex_r === hoveredHex.r);
    }, [hoveredHex, agents]);

    return (
      <div className="relative h-full w-full cursor-crosshair overflow-hidden bg-[#04070d]">
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
                onHexClick={onHexClick}
                onHexHover={handleHexHover}
                onHexContextMenu={handleHexContextMenu}
              />
              {agents.map((agent) => (
                <AgentMesh
                  key={agent.agent_id}
                  agent={agent}
                  hexSize={hexSize}
                  isSelected={
                    selectedAgentId === agent.agent_id ||
                    (selectedHex?.q === agent.hex_q && selectedHex?.r === agent.hex_r)
                  }
                />
              ))}
              {hoveredAgent &&
                hoveredAgent.hex_q !== undefined &&
                hoveredAgent.hex_r !== undefined && (
                  <mesh
                    position={[
                      hexToPixel(hoveredAgent.hex_q, hoveredAgent.hex_r, hexSize).x,
                      0.15,
                      hexToPixel(hoveredAgent.hex_q, hoveredAgent.hex_r, hexSize).y,
                    ]}
                    rotation={[-Math.PI / 2, 0, 0]}
                  >
                    <ringGeometry args={[hexSize * 0.8, hexSize * 0.9, 32]} />
                    <meshBasicMaterial
                      color="#60a5fa"
                      transparent
                      opacity={0.6}
                      side={DoubleSide}
                    />
                  </mesh>
                )}
              {edges.map((edge) => (
                <CorridorMesh key={edge.id} edge={edge} hexSize={hexSize} />
              ))}
              <MessageFlowParticles ref={particlesRef} agents={agents} hexSize={hexSize} />
            </HexScene>
            <CameraAnimator targetPosition={zoomTarget} />
          </Canvas>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-zinc-500">
            Initializing 3D view...
          </div>
        )}
      </div>
    );
  }
);

HexCanvas3D.displayName = 'HexCanvas3D';
