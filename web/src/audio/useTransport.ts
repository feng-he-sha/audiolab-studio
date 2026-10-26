/** React binding for the imperative Transport engine. */
import { useEffect, useRef, useState } from "react";
import { Transport, type TransportInit, type TransportSnapshot, type TransportTrack } from "./Transport";

export interface UseTransportResult {
  transport: Transport | null;
  snapshot: TransportSnapshot;
  time: number;
}

const INITIAL_SNAPSHOT: TransportSnapshot = {
  mode: "idle",
  playing: false,
  duration: 0,
  time: 0,
  loop: false,
  ready: false,
  error: "",
  loading: false,
};

/**
 * Creates a Transport for the given tracks and reloads it whenever `key`
 * changes. The engine is disposed on unmount so switching tabs stops audio.
 */
export function useTransport(
  key: string,
  tracks: TransportTrack[],
  init: TransportInit,
): UseTransportResult {
  const transportRef = useRef<Transport | null>(null);
  const [transport, setTransport] = useState<Transport | null>(null);
  const [snapshot, setSnapshot] = useState<TransportSnapshot>(INITIAL_SNAPSHOT);
  const [time, setTime] = useState(0);
  const tracksRef = useRef(tracks);
  const initRef = useRef(init);
  tracksRef.current = tracks;
  initRef.current = init;

  useEffect(() => {
    const engine = new Transport(initRef.current);
    transportRef.current = engine;
    setTransport(engine);
    const unsubscribeState = engine.subscribeState((value) => setSnapshot({ ...value }));
    const unsubscribeTime = engine.subscribeTime((value) => setTime(value));
    void engine.load(tracksRef.current);
    return () => {
      unsubscribeState();
      unsubscribeTime();
      engine.dispose();
      transportRef.current = null;
      setTransport(null);
      setSnapshot(INITIAL_SNAPSHOT);
      setTime(0);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return { transport, snapshot, time };
}
