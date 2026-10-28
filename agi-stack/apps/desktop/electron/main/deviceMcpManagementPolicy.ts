import { requireDeviceMcpRequestV2 } from '../../src/api/deviceMcpContractV2';

export async function executeDeviceMcpManagementV2(
  args: unknown,
  authorizeOwner: () => number,
  invoke: (args: Record<string, unknown>) => Promise<unknown>,
): Promise<unknown> {
  const owner = authorizeOwner();
  const request = requireDeviceMcpRequestV2(args);
  const result = await invoke(request);
  if (authorizeOwner() !== owner) throw new Error('device_mcp_owner_changed');
  return result;
}
