/** Suspend renderer delivery creation and submission for the entire identity mutation. */
export class RendererDeliveryAdmissionV2 {
  private transitions = 0;
  private tail: Promise<unknown> = Promise.resolve();

  assertAdmitted(): void {
    if (this.transitions !== 0) throw new Error('desktop_renderer_authority_transition');
  }

  async transition<T>(retire: () => Promise<unknown>, operation: () => Promise<T>): Promise<T> {
    this.transitions += 1;
    try {
      const pending = Promise.allSettled([this.tail, retire()]).then(([, retirement]) => {
        if (retirement.status === 'rejected') throw retirement.reason;
        return operation();
      });
      this.tail = pending.catch(() => undefined);
      return await pending;
    } finally {
      this.transitions -= 1;
    }
  }
}
