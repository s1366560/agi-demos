export class InstanceTemplatesUnavailableError extends Error {
  readonly reasonCode: string;

  constructor(reasonCode: string) {
    super(reasonCode);
    this.name = 'InstanceTemplatesUnavailableError';
    this.reasonCode = reasonCode;
  }
}
