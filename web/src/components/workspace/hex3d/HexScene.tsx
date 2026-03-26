export function HexScene({ children }: { children: React.ReactNode }) {
  return (
    <group>
      <ambientLight intensity={0.6} />
      <directionalLight position={[5, 10, 5]} intensity={0.8} />
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.2, 0]} receiveShadow>
        <planeGeometry args={[1000, 1000]} />
        <meshStandardMaterial color="#e2e8f0" transparent opacity={0.3} depthWrite={false} />
      </mesh>
      {children}
    </group>
  );
}
