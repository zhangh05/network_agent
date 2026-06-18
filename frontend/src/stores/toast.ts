/**
 * Toast store — for global error/success messages. Pages dispatch
 * `useToastStore.getState().show(...)` and the ToastHost renders them.
 */

import { create } from "zustand";

export interface ToastMessage {
  id: string;
  kind: "info" | "success" | "warning" | "error";
  title: string;
  body?: string;
  request_id?: string;
}

interface ToastState {
  messages: ToastMessage[];
  show: (msg: Omit<ToastMessage, "id">) => void;
  dismiss: (id: string) => void;
}

let toastSeq = 0;
const _timeouts = new Map<string, ReturnType<typeof setTimeout>>();

export const useToastStore = create<ToastState>((set) => ({
  messages: [],
  show: (msg) => {
    toastSeq += 1;
    const id = `toast-${Date.now()}-${toastSeq}`;
    set((prev) => ({ messages: [...prev.messages, { ...msg, id }] }));
    const timer = setTimeout(() => {
      _timeouts.delete(id);
      set((prev) => ({ messages: prev.messages.filter((m) => m.id !== id) }));
    }, 6000);
    _timeouts.set(id, timer);
  },
  dismiss: (id) => {
    const timer = _timeouts.get(id);
    if (timer) { clearTimeout(timer); _timeouts.delete(id); }
    set((prev) => ({ messages: prev.messages.filter((m) => m.id !== id) }));
  },
}));
