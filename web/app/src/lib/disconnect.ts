import { deleteDevice } from "../api/client";
import { CONN_CHANGED, loadConn, loadDeviceId } from "./connection";
import { hardReplace } from "./nav";
import { clearPhotoCache } from "./photoCache";
import { unsubscribePush } from "./push";
import { clearDeviceData } from "./snapshot";
import { applyPalette, applyTheme, DEFAULT_PALETTE } from "./theme";

// "이 기기 연결 해제" (SP5 4.7, device pairing spec 5.4). When the saved token is a device token
// (`deviceId`, by default the one saved at connect) the BE revokes it first (after the push
// subscription goes, which needs the token); then every mp.* key, snapshots and parts go, whatever
// the BE or the browser answers (spec 5.5.7). Ends with a full load of /connect/: the chat sheet,
// catalog and polls of the old BE leave memory too.
export async function disconnectThisDevice({ deviceId = loadDeviceId() }: { deviceId?: number | null } = {}): Promise<void> {
  try {
    try {
      await unsubscribePush();
    } catch {
      // spec 5.5.7: the device is cleared even when the BE or the browser cannot drop the subscription
    }
    const conn = loadConn();
    if (deviceId !== null && conn) {
      try {
        await deleteDevice(deviceId, conn); // any answer: the device is cleared anyway
      } catch {
        // as above
      }
    }
    await clearDeviceData();
    clearPhotoCache(); // SP10 7.3: the photos of this BE leave memory too
    applyTheme("system");
    applyPalette(DEFAULT_PALETTE);
    window.dispatchEvent(new Event(CONN_CHANGED));
  } finally {
    hardReplace("/connect/");
  }
}
