import { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { Cylinder, Sphere, Billboard, Text } from '@react-three/drei';
import type { Group } from 'three';
import { hexToPixel } from '@/components/workspace/hex/useHexLayout';
import type { WorkspaceAgent } from '@/types/workspace';

interface AgentMeshProps {
  agent: WorkspaceAgent;
  hexSize: number;
  isSelected?: boolean;
}

export function AgentMesh({ agent, hexSize, isSelected }: AgentMeshProps) {
  const groupRef = useRef<Group>(null);

  useFrame(({ clock }) => {
    if (groupRef.current) {
      groupRef.current.position.y = 0.5 + Math.sin(clock.elapsedTime * 2) * 0.05;
    }
  });

  if (agent.hex_q === undefined || agent.hex_r === undefined) {
    return null;
  }

  const { x, y: z } = hexToPixel(agent.hex_q, agent.hex_r, hexSize);
  const color = agent.theme_color ?? '#3b82f6';

  return (
    <group position={[x, 0.5, z]} ref={groupRef}>
      <Cylinder args={[0.3 * hexSize, 0.35 * hexSize, 0.6 * hexSize]} position={[0, 0, 0]}>
        <meshStandardMaterial color={color} />
      </Cylinder>
      <Sphere args={[0.2 * hexSize, 16, 16]} position={[0, 0.4 * hexSize, 0]}>
        <meshStandardMaterial color={color} />
      </Sphere>
      <Billboard position={[0, 0.8 * hexSize, 0]}>
        <Text fontSize={0.3} color="#1e293b" anchorY="bottom">
          {agent.display_name || agent.agent_id}
        </Text>
      </Billboard>
      {isSelected && (
        <mesh position={[0, -0.2 * hexSize, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[0.4 * hexSize, 0.45 * hexSize, 32]} />
          <meshBasicMaterial color="#3b82f6" side={2} />
        </mesh>
      )}
    </group>
  );
}
