import { useMemo, useRef, useEffect } from 'react';

import { useFrame } from '@react-three/fiber';
import { InstancedMesh, CylinderGeometry, Color, Object3D, BufferGeometry, Mesh } from 'three';
import { computeBoundsTree, disposeBoundsTree, acceleratedRaycast } from 'three-mesh-bvh';

import { hexToPixel } from '@/components/workspace/hex/useHexLayout';

import type { WorkspaceAgent, TopologyNode } from '@/types/workspace';

import type { HexCoordinates } from './useHex3DPick';
import type { ThreeEvent } from '@react-three/fiber';


BufferGeometry.prototype.computeBoundsTree = computeBoundsTree as unknown as typeof BufferGeometry.prototype.computeBoundsTree;
BufferGeometry.prototype.disposeBoundsTree = disposeBoundsTree as unknown as typeof BufferGeometry.prototype.disposeBoundsTree;
Mesh.prototype.raycast = acceleratedRaycast as unknown as typeof Mesh.prototype.raycast;

interface HexInstancesProps {
  nodes: { q: number; r: number }[];
  hexSize: number;
  agents: WorkspaceAgent[];
  topologyNodes: TopologyNode[];
  selectedHex: HexCoordinates | null;
  hoveredHex: HexCoordinates | null;
  onHexClick: (q: number, r: number) => void;
  onHexHover: (q: number | null, r: number | null) => void;
  onHexContextMenu: (q: number, r: number, e: MouseEvent) => void;
}

const colorDefault = new Color('#e2e8f0');
const colorOccupied = new Color('#bfdbfe');
const colorHovered = new Color('#93c5fd');
const colorSelected = new Color('#3b82f6');

export function HexInstances({
  nodes,
  hexSize,
  agents,
  topologyNodes,
  selectedHex,
  hoveredHex,
  onHexClick,
  onHexHover,
  onHexContextMenu,
}: HexInstancesProps) {
  const meshRef = useRef<InstancedMesh>(null);
  const tempObject = useMemo(() => new Object3D(), []);

  const geometry = useMemo(() => {
    const geo = new CylinderGeometry(hexSize * 0.95, hexSize * 0.95, 0.2, 6);
    geo.computeBoundsTree();
    return geo;
  }, [hexSize]);

  const occupiedSet = useMemo(() => {
    const set = new Set<string>();
    agents.forEach((a) => {
      if (a.hex_q !== undefined && a.hex_r !== undefined) {
        set.add(String(a.hex_q) + ',' + String(a.hex_r));
      }
    });
    topologyNodes.forEach((n) => {
      if (n.hex_q !== undefined && n.hex_r !== undefined) {
        set.add(String(n.hex_q) + ',' + String(n.hex_r));
      }
    });
    return set;
  }, [agents, topologyNodes]);

  useEffect(() => {
    const mesh = meshRef.current;
    if (!mesh) return;
    
    nodes.forEach((node, i) => {
      const { x, y: z } = hexToPixel(node.q, node.r, hexSize);
      tempObject.position.set(x, 0.1, z);
      tempObject.rotation.y = Math.PI / 6;
      tempObject.updateMatrix();
      mesh.setMatrixAt(i, tempObject.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
  }, [nodes, hexSize, tempObject]);

  useFrame(() => {
    const mesh = meshRef.current;
    if (!mesh) return;
    
    nodes.forEach((node, i) => {
      const isSelected = selectedHex !== null && selectedHex.q === node.q && selectedHex.r === node.r;
      const isHovered = hoveredHex !== null && hoveredHex.q === node.q && hoveredHex.r === node.r;
      const isOccupied = occupiedSet.has(String(node.q) + ',' + String(node.r));

      let color = colorDefault;
      if (isSelected) {
        color = colorSelected;
      } else if (isHovered) {
        color = colorHovered;
      } else if (isOccupied) {
        color = colorOccupied;
      }

      mesh.setColorAt(i, color);
    });
    if (mesh.instanceColor) {
      mesh.instanceColor.needsUpdate = true;
    }
  });

  const handlePointerMove = (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation();
    if (e.instanceId !== undefined) {
      const node = nodes[e.instanceId];
      if (node) {
        onHexHover(node.q, node.r);
      }
    }
  };

  const handlePointerOut = () => {
    onHexHover(null, null);
  };

  const handleClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    if (e.instanceId !== undefined) {
      const node = nodes[e.instanceId];
      if (node) {
        onHexClick(node.q, node.r);
      }
    }
  };

  const handleContextMenu = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    if (e.instanceId !== undefined) {
      const node = nodes[e.instanceId];
      if (node) {
        onHexContextMenu(node.q, node.r, e.nativeEvent);
      }
    }
  };

  return (
    <instancedMesh
      ref={meshRef}
      args={[geometry, undefined, nodes.length]}
      onPointerMove={handlePointerMove}
      onPointerOut={handlePointerOut}
      onClick={handleClick}
      onContextMenu={handleContextMenu}
    >
      <meshStandardMaterial />
    </instancedMesh>
  );
}
