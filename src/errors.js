export class WorkerError extends Error {
  constructor(code, message, status, megaCode = null) {
    super(message);
    this.code = code;
    this.status = status;
    this.megaCode = megaCode;
  }
}
