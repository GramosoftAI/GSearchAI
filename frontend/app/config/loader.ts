type Listener = (pending: number) => void;
let pending = 0;
const listeners = new Set<Listener>();
export function subscribe(listener: Listener) {
  listeners.add(listener);
  listener(pending);
  return () => listeners.delete(listener);
}
export function inc() {
  pending += 1;
  for (const l of listeners) l(pending);
}
export function dec() {
  pending = Math.max(0, pending - 1);
  for (const l of listeners) l(pending);
}
