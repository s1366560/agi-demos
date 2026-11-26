// An address a page asked the router for, and when. The router arrives at once,
// or something kept it from arriving: that request is not allowed to vouch later.
export interface RequestedAddress {
  readonly address: string;
  readonly at: number;
}

export const ADDRESS_ARRIVAL_MS = 15000;

/** Whether a page stays mounted at this address: it asked for it, and the router has just arrived. */
export function arrived(
  requested: RequestedAddress | null,
  address: string,
  now: number,
): requested is RequestedAddress {
  return (
    requested?.address === address && now - requested.at < ADDRESS_ARRIVAL_MS
  );
}
