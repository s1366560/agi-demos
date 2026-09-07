import { expect, it, vi } from 'vitest';
import { RendererDeliveryAdmissionV2 } from '../../../../agi-stack/apps/desktop/electron/main/rendererDeliveryAdmissionV2';

it('blocks creation and submission until all overlapping identity transitions finish', async () => {
  const gate = new RendererDeliveryAdmissionV2();
  let releaseRetirement!: () => void;
  let releaseMutation!: () => void;
  const retirement = new Promise<void>((resolve) => { releaseRetirement = resolve; });
  const mutation = new Promise<void>((resolve) => { releaseMutation = resolve; });
  const operation = vi.fn(() => mutation);
  const first = gate.transition(() => retirement, operation);
  expect(() => gate.assertAdmitted()).toThrow('desktop_renderer_authority_transition');
  expect(operation).not.toHaveBeenCalled();
  releaseRetirement();
  await Promise.resolve();
  expect(operation).toHaveBeenCalledOnce();
  await gate.transition(async () => undefined, async () => undefined);
  expect(() => gate.assertAdmitted()).toThrow('desktop_renderer_authority_transition');
  releaseMutation();
  await first;
  expect(() => gate.assertAdmitted()).not.toThrow();
});

it('does not mutate identity if retirement fails and always releases the admission barrier', async () => {
  const gate = new RendererDeliveryAdmissionV2();
  const operation = vi.fn();
  await expect(gate.transition(async () => { throw new Error('retirement'); }, operation)).rejects.toThrow('retirement');
  expect(operation).not.toHaveBeenCalled();
  expect(() => gate.assertAdmitted()).not.toThrow();
  await expect(gate.transition(async () => undefined, async () => { throw new Error('mutation'); })).rejects.toThrow('mutation');
  expect(() => gate.assertAdmitted()).not.toThrow();
});
