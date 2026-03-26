import { useMemo, useRef } from 'react';

import { Box, Sphere, Cylinder, Billboard, Text, Circle, Plane, Line } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';

import { hexToPixel } from '@/components/workspace/hex/useHexLayout';

import type { WorkspaceAgent } from '@/types/workspace';

interface AgentMeshProps {
  agent: WorkspaceAgent;
  hexSize: number;
  isSelected?: boolean;
}

type AnimState = 'idle' | 'working' | 'thinking' | 'error';

function resolveAnimState(status?: string): AnimState {
  if (!status) return 'idle';
  const s = status.toLowerCase();
  if (
    ['running', 'active', 'learning', 'restarting', 'deploying', 'updating', 'creating'].includes(s)
  ) {
    return 'working';
  }
  if (s === 'thinking') return 'thinking';
  if (s === 'error' || s === 'failed') return 'error';
  return 'idle';
}

const STATUS_ACCENT: Record<string, string> = {
  running: '#4ade80',
  active: '#4ade80',
  learning: '#60a5fa',
  thinking: '#a78bfa',
  pending: '#fbbf24',
  idle: '#8b8b9e',
  error: '#f87171',
  failed: '#f87171',
};

const DEFAULT_ACCENT = '#67e8f9';

const MouthPoints: [number, number, number][] = [
  [-0.035, 0, 0],
  [0, -0.015, 0],
  [0.035, 0, 0],
];

export function AgentMesh({ agent, hexSize, isSelected }: AgentMeshProps) {
  const mainGroupRef = useRef<THREE.Group>(null);
  const headGroupRef = useRef<THREE.Group>(null);
  const leftArmGroupRef = useRef<THREE.Group>(null);
  const rightArmGroupRef = useRef<THREE.Group>(null);
  const statusRingRef = useRef<THREE.Mesh>(null);

  const screenMatRef = useRef<THREE.MeshBasicMaterial>(null);
  const antennaMatRefL = useRef<THREE.MeshStandardMaterial>(null);
  const antennaMatRefR = useRef<THREE.MeshStandardMaterial>(null);
  const chestLightMatRef = useRef<THREE.MeshBasicMaterial>(null);
  const statusRingMatRef = useRef<THREE.MeshBasicMaterial>(null);

  const tb1Ref = useRef<THREE.Mesh>(null);
  const tb2Ref = useRef<THREE.Mesh>(null);
  const tb3Ref = useRef<THREE.Mesh>(null);
  const tbm1Ref = useRef<THREE.MeshBasicMaterial>(null);
  const tbm2Ref = useRef<THREE.MeshBasicMaterial>(null);
  const tbm3Ref = useRef<THREE.MeshBasicMaterial>(null);

  const animState = resolveAnimState(agent.status);

  const baseColor = agent.theme_color ?? '#7a8a9a';
  const accentColor = agent.status
    ? (STATUS_ACCENT[agent.status.toLowerCase()] ?? DEFAULT_ACCENT)
    : DEFAULT_ACCENT;

  const { mainColor, secColor, terColor } = useMemo(() => {
    const c = new THREE.Color(baseColor);
    const hsl = { h: 0, s: 0, l: 0 };
    c.getHSL(hsl);
    return {
      mainColor: new THREE.Color().setHSL(hsl.h, hsl.s, hsl.l),
      secColor: new THREE.Color().setHSL(hsl.h, hsl.s * 0.9, Math.min(hsl.l + 0.08, 1)),
      terColor: new THREE.Color().setHSL(hsl.h, hsl.s * 0.8, Math.min(hsl.l + 0.15, 1)),
    };
  }, [baseColor]);

  useFrame(({ clock }) => {
    const time = clock.elapsedTime;

    if (statusRingRef.current) {
      statusRingRef.current.rotation.z -= animState === 'working' ? 0.03 : 0.015;
    }

    if (antennaMatRefL.current && antennaMatRefR.current) {
      const emissiveInt = 0.5 + Math.sin(time * 3) * 0.3;
      antennaMatRefL.current.emissiveIntensity = emissiveInt;
      antennaMatRefR.current.emissiveIntensity = emissiveInt;
    }
    if (chestLightMatRef.current) {
      chestLightMatRef.current.opacity = 0.6 + Math.sin(time * 2) * 0.3;
    }
    if (screenMatRef.current) {
      screenMatRef.current.opacity = 0.12 + Math.sin(time * 1.5) * 0.05;
    }

    // Default resets / damping
    if (mainGroupRef.current) {
      mainGroupRef.current.position.x *= 0.92;
    }
    if (leftArmGroupRef.current) {
      leftArmGroupRef.current.rotation.x *= 0.92;
      leftArmGroupRef.current.rotation.z *= 0.92;
    }
    if (rightArmGroupRef.current) {
      rightArmGroupRef.current.rotation.x *= 0.92;
      rightArmGroupRef.current.rotation.z *= 0.92;
    }
    if (headGroupRef.current) {
      headGroupRef.current.rotation.z *= 0.92;
    }

    // Animation states
    if (animState === 'idle') {
      if (mainGroupRef.current) mainGroupRef.current.position.y = Math.sin(time * 1.5) * 0.02;
      if (leftArmGroupRef.current) leftArmGroupRef.current.rotation.x = Math.sin(time * 1.2) * 0.1;
      if (rightArmGroupRef.current)
        rightArmGroupRef.current.rotation.x = Math.sin(time * 1.2 + Math.PI) * 0.1;
    } else if (animState === 'working') {
      if (mainGroupRef.current)
        mainGroupRef.current.position.y = Math.abs(Math.sin(time * 4)) * 0.015;
      if (rightArmGroupRef.current) rightArmGroupRef.current.rotation.x = Math.sin(time * 6) * 0.4;
      if (leftArmGroupRef.current) leftArmGroupRef.current.rotation.x = Math.sin(time * 2) * 0.08;
      if (screenMatRef.current)
        screenMatRef.current.opacity = 0.1 + Math.abs(Math.sin(time * 4)) * 0.15;
    } else if (animState === 'thinking') {
      if (mainGroupRef.current) mainGroupRef.current.position.y = Math.sin(time) * 0.01;
      if (headGroupRef.current) headGroupRef.current.rotation.z = Math.sin(time * 0.8) * 0.1 + 0.15;
      if (rightArmGroupRef.current) {
        rightArmGroupRef.current.rotation.x = -0.8;
        rightArmGroupRef.current.rotation.z = 0.3;
      }
      if (leftArmGroupRef.current) leftArmGroupRef.current.rotation.x = 0.1;
    } else {
      // error state
      if (mainGroupRef.current) {
        mainGroupRef.current.position.x = Math.sin(time * 20) * 0.02;
        mainGroupRef.current.position.y = 0;
      }
      if (statusRingMatRef.current)
        statusRingMatRef.current.opacity = 0.3 + Math.sin(time * 8) * 0.3;
      if (screenMatRef.current) screenMatRef.current.opacity = Math.sin(time * 8) > 0 ? 0.2 : 0.05;
    }

    // Thought bubbles
    const showBubbles = animState === 'thinking';
    const bubbles = [
      { m: tb1Ref.current, mat: tbm1Ref.current, y: 0.95 },
      { m: tb2Ref.current, mat: tbm2Ref.current, y: 1.05 },
      { m: tb3Ref.current, mat: tbm3Ref.current, y: 1.18 },
    ];

    bubbles.forEach((b, i) => {
      if (!b.m || !b.mat) return;
      if (showBubbles) {
        b.m.visible = true;
        b.mat.opacity = Math.min(b.mat.opacity + 0.03, 0.85);
        b.m.position.y = b.y + Math.sin(time * 2 + i) * 0.05;
      } else {
        b.mat.opacity = Math.max(b.mat.opacity - 0.05, 0);
        if (b.mat.opacity <= 0) b.m.visible = false;
      }
    });
  });

  if (agent.hex_q === undefined || agent.hex_r === undefined) {
    return null;
  }

  const { x, y: z } = hexToPixel(agent.hex_q, agent.hex_r, hexSize);

  const scale = hexSize * 1.5;

  return (
    <group position={[x, 0.5, z]}>
      <group scale={scale}>
        <group ref={mainGroupRef}>
          {/* Head */}
          <group ref={headGroupRef} position={[0, 0.54, 0]}>
            <Box args={[0.38, 0.3, 0.28]}>
              <meshStandardMaterial color={mainColor} metalness={0.7} roughness={0.3} />
            </Box>
            <Plane args={[0.34, 0.26]} position={[0, 0, 0.141]}>
              <meshBasicMaterial color={accentColor} transparent opacity={0.3} />
            </Plane>
            <Plane args={[0.32, 0.24]} position={[0, 0, 0.142]}>
              <meshBasicMaterial
                color={accentColor}
                transparent
                opacity={0.15}
                ref={screenMatRef}
              />
            </Plane>
            <Circle args={[0.035, 16]} position={[-0.065, 0.03, 0.143]}>
              <meshBasicMaterial color={accentColor} />
            </Circle>
            <Circle args={[0.035, 16]} position={[0.065, 0.03, 0.143]}>
              <meshBasicMaterial color={accentColor} />
            </Circle>
            <Line
              points={MouthPoints}
              color={accentColor}
              lineWidth={2}
              position={[0, -0.04, 0.143]}
            />

            {/* Antennas */}
            <Cylinder args={[0.012, 0.015, 0.08, 8]} position={[-0.08, 0.19, 0]}>
              <meshStandardMaterial color={terColor} metalness={0.7} roughness={0.3} />
            </Cylinder>
            <Sphere args={[0.025, 8, 8]} position={[-0.08, 0.25, 0]}>
              <meshStandardMaterial
                color={accentColor}
                emissive={accentColor}
                ref={antennaMatRefL}
              />
            </Sphere>
            <Cylinder args={[0.012, 0.015, 0.08, 8]} position={[0.08, 0.19, 0]}>
              <meshStandardMaterial color={terColor} metalness={0.7} roughness={0.3} />
            </Cylinder>
            <Sphere args={[0.025, 8, 8]} position={[0.08, 0.25, 0]}>
              <meshStandardMaterial
                color={accentColor}
                emissive={accentColor}
                ref={antennaMatRefR}
              />
            </Sphere>
          </group>

          {/* Torso */}
          <Box args={[0.34, 0.28, 0.24]} position={[0, 0.34, 0]}>
            <meshStandardMaterial color={mainColor} metalness={0.7} roughness={0.3} />
          </Box>
          <Plane args={[0.14, 0.1]} position={[0, 0.36, 0.121]}>
            <meshStandardMaterial color="#2a3a4e" transparent opacity={0.8} />
          </Plane>
          <Circle args={[0.025, 16]} position={[0, 0.34, 0.123]}>
            <meshBasicMaterial
              color={accentColor}
              transparent
              opacity={0.8}
              ref={chestLightMatRef}
            />
          </Circle>

          {/* Left Arm */}
          <group ref={leftArmGroupRef} position={[-0.19, 0.42, 0]}>
            <Sphere args={[0.04, 8, 8]}>
              <meshStandardMaterial color={terColor} metalness={0.7} roughness={0.3} />
            </Sphere>
            <Cylinder args={[0.028, 0.032, 0.12, 8]} position={[0, -0.08, 0]}>
              <meshStandardMaterial color={secColor} metalness={0.6} roughness={0.4} />
            </Cylinder>
            <Sphere args={[0.038, 8, 8]} position={[0, -0.16, 0]} scale={[1.1, 0.7, 1.1]}>
              <meshStandardMaterial color={terColor} metalness={0.7} roughness={0.3} />
            </Sphere>
          </group>

          {/* Right Arm */}
          <group ref={rightArmGroupRef} position={[0.19, 0.42, 0]}>
            <Sphere args={[0.04, 8, 8]}>
              <meshStandardMaterial color={terColor} metalness={0.7} roughness={0.3} />
            </Sphere>
            <Cylinder args={[0.028, 0.032, 0.12, 8]} position={[0, -0.08, 0]}>
              <meshStandardMaterial color={secColor} metalness={0.6} roughness={0.4} />
            </Cylinder>
            <Sphere args={[0.038, 8, 8]} position={[0, -0.16, 0]} scale={[1.1, 0.7, 1.1]}>
              <meshStandardMaterial color={terColor} metalness={0.7} roughness={0.3} />
            </Sphere>
          </group>
        </group>

        {/* Status Ring */}
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.01, 0]} ref={statusRingRef}>
          <ringGeometry args={[0.28, 0.32, 32]} />
          <meshBasicMaterial
            color={accentColor}
            transparent
            opacity={0.6}
            side={THREE.DoubleSide}
            ref={statusRingMatRef}
          />
        </mesh>

        {/* Thought Bubbles */}
        <Circle args={[0.04, 16]} position={[0.15, 0.95, 0.1]} ref={tb1Ref} visible={false}>
          <meshBasicMaterial
            color={accentColor}
            transparent
            opacity={0}
            side={THREE.DoubleSide}
            ref={tbm1Ref}
          />
        </Circle>
        <Circle args={[0.06, 16]} position={[0.22, 1.05, 0.15]} ref={tb2Ref} visible={false}>
          <meshBasicMaterial
            color={accentColor}
            transparent
            opacity={0}
            side={THREE.DoubleSide}
            ref={tbm2Ref}
          />
        </Circle>
        <Circle args={[0.09, 16]} position={[0.12, 1.18, 0.1]} ref={tb3Ref} visible={false}>
          <meshBasicMaterial
            color={accentColor}
            transparent
            opacity={0}
            side={THREE.DoubleSide}
            ref={tbm3Ref}
          />
        </Circle>
      </group>

      <Billboard position={[0, 0.8 * hexSize, 0]}>
        <Text fontSize={0.3} color="#1e293b" anchorY="bottom">
          {agent.display_name || agent.agent_id}
        </Text>
      </Billboard>
      {isSelected && (
        <mesh position={[0, -0.2 * hexSize, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[0.4 * hexSize, 0.45 * hexSize, 32]} />
          <meshBasicMaterial color="#3b82f6" side={THREE.DoubleSide} />
        </mesh>
      )}
    </group>
  );
}
