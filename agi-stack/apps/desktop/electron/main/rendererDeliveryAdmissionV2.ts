/** Suspend renderer delivery creation and submission for the entire identity mutation. */
export class RendererDeliveryAdmissionV2 {
  private transitions = 0;

  assertAdmitted(): void {
    if (this.transitions !== 0) throw new Error('desktop_renderer_authority_transition');
  }

  async transition<T>(retire: () => Promise<unknown>, operation: () => Promise<T>): Promise<T> {
    this.transitions += 1;
    try {
      await retire();
      return await operation();
    } finally {
      this.transitions -= 1;
    }
  }
}
