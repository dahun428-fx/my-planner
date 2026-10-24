// client_msg_id for /actions, /undo and /chat (SP3-4 6.1): a new value per action.
export function newClientMsgId(): string {
  return crypto.randomUUID();
}
