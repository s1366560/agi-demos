export class PluginProtocolV2Error extends Error {
  constructor(
    readonly code: string,
    message: string
  ) {
    super(message);
    this.name = 'PluginProtocolV2Error';
  }
}

export class RuntimeV2Error extends Error {
  constructor(
    readonly code: string,
    message: string
  ) {
    super(message);
    this.name = 'RuntimeV2Error';
  }
}
