import { Line } from '@react-three/drei';
import { hexToPixel } from '@/components/workspace/hex/useHexLayout';
import type { TopologyEdge } from '@/types/workspace';

interface CorridorMeshProps {
  edge: TopologyEdge;
  hexSize: number;
}

export function CorridorMesh({ edge, hexSize }: CorridorMeshProps) {
  if (
    edge.source_hex_q === undefined ||
    edge.source_hex_r === undefined ||
    edge.target_hex_q === undefined ||
    edge.target_hex_r === undefined
  ) {
    return null;
  }

  const startPixel = hexToPixel(edge.source_hex_q, edge.source_hex_r, hexSize);
  const endPixel = hexToPixel(edge.target_hex_q, edge.target_hex_r, hexSize);

  const start: [number, number, number] = [startPixel.x, 0.15, startPixel.y];
  const end: [number, number, number] = [endPixel.x, 0.15, endPixel.y];

  return (
    <group>
      <Line points={[start, end]} color="#94a3b8" lineWidth={2} dashed={false} />
      <Line points={[start, end]} color="#94a3b8" lineWidth={6} dashed={false} transparent opacity={0.2} />
    </group>
  );
}
