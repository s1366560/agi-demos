import React, { forwardRef, useImperativeHandle, useRef, useState } from 'react';

import { Sphere } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import { Vector3, Group, Mesh, MeshStandardMaterial } from 'three';

import { hexToPixel } from '@/components/workspace/hex/useHexLayout';

import type { WorkspaceAgent } from '@/types/workspace';

export interface MessageFlowParticlesProps {
  agents: WorkspaceAgent[];
  hexSize: number;
}

export interface MessageFlowParticlesRef {
  triggerFlow: (fromAgentId: string, toAgentId: string) => void;
}

interface ActiveFlow {
  id: string;
  fromPos: Vector3;
  toPos: Vector3;
  progress: number;
  color: string;
}

interface SingleFlowProps {
  flow: ActiveFlow;
  hexSize: number;
  onComplete: (id: string) => void;
}

function SingleFlow({ flow, hexSize, onComplete }: SingleFlowProps) {
  const groupRef = useRef<Group>(null);
  const particles = 4;
  const stagger = 0.08;
  const speed = 0.8;
  
  const particleRefs = useRef<(Mesh | null)[]>([]);
  const materialRefs = useRef<(MeshStandardMaterial | null)[]>([]);

  const progressRef = useRef(flow.progress);

  useFrame((_, delta) => {
    progressRef.current += delta * speed;
    const currentProgress = progressRef.current;
    
    if (currentProgress > 1 + particles * stagger) {
      onComplete(flow.id);
      return;
    }

    for (let i = 0; i < particles; i++) {
      const pProgress = currentProgress - i * stagger;
      const mesh = particleRefs.current[i];
      const mat = materialRefs.current[i];
      
      if (!mesh || !mat) continue;

      if (pProgress < 0 || pProgress > 1) {
        mesh.visible = false;
      } else {
        mesh.visible = true;
        mesh.position.lerpVectors(flow.fromPos, flow.toPos, pProgress);
        
        let opacity = 1;
        if (pProgress < 0.1) opacity = pProgress / 0.1;
        else if (pProgress > 0.9) opacity = (1 - pProgress) / 0.1;
        
        const scale = Math.max(0.2, 1 - (i * 0.15));
        mesh.scale.setScalar(scale);

        mat.opacity = opacity;
        mat.transparent = true;
      }
    }
  });

  return (
    <group ref={groupRef}>
      {Array.from({ length: particles }).map((_, i) => {
        const key = `particle-${String(i)}`;
        return (
          <Sphere
            key={key}
            ref={(el) => { particleRefs.current[i] = el; }}
            args={[0.06 * hexSize, 16, 16]}
            visible={false}
          >
            <meshStandardMaterial
              ref={(el) => { materialRefs.current[i] = el; }}
              color={flow.color}
              emissive={flow.color}
              emissiveIntensity={2}
              toneMapped={false}
            />
          </Sphere>
        );
      })}
    </group>
  );
}

export const MessageFlowParticles = forwardRef<MessageFlowParticlesRef, MessageFlowParticlesProps>(
  ({ agents, hexSize }, ref) => {
    const [flows, setFlows] = useState<ActiveFlow[]>([]);
    
    const flowsRef = useRef<ActiveFlow[]>([]);

    useImperativeHandle(ref, () => ({
      triggerFlow: (fromAgentId: string, toAgentId: string) => {
        const fromAgent = agents.find(a => a.agent_id === fromAgentId);
        const toAgent = agents.find(a => a.agent_id === toAgentId);

        if (!fromAgent || !toAgent || 
            fromAgent.hex_q === undefined || fromAgent.hex_r === undefined ||
            toAgent.hex_q === undefined || toAgent.hex_r === undefined) {
          return;
        }

        const fromPixel = hexToPixel(fromAgent.hex_q, fromAgent.hex_r, hexSize);
        const toPixel = hexToPixel(toAgent.hex_q, toAgent.hex_r, hexSize);

        const newFlow: ActiveFlow = {
          id: Math.random().toString(36).substring(2, 9),
          fromPos: new Vector3(fromPixel.x, 0.3, fromPixel.y),
          toPos: new Vector3(toPixel.x, 0.3, toPixel.y),
          progress: 0,
          color: fromAgent.theme_color ?? '#3b82f6'
        };

        flowsRef.current = [...flowsRef.current, newFlow];
        setFlows(flowsRef.current);
      }
    }));

    const handleComplete = (id: string) => {
      flowsRef.current = flowsRef.current.filter(f => f.id !== id);
      setFlows(flowsRef.current);
    };

    return (
      <group>
        {flows.map(flow => (
          <SingleFlow 
            key={flow.id} 
            flow={flow} 
            hexSize={hexSize} 
            onComplete={handleComplete} 
          />
        ))}
      </group>
    );
  }
);

MessageFlowParticles.displayName = 'MessageFlowParticles';
