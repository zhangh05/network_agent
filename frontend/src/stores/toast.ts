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
export const useToastStore = create<ToastState>((set) => ({
  messages: [],
  show: (msg) => {
    toastSeq += 1;
    const id = `toast-${Date.now()}-${toastSeq}`;
    // Use functional set to avoid races when multiple toasts fire in same batch
    set((prev) => ({ messages: [...prev.messages, { ...msg, id }] }));
    setTimeout(() => {
      set((prev) => ({ messages: prev.messages.filter((m) => m.id !== id) }));
    }, 6000);
  },
  dismiss: (id) =>
    set((prev) => ({ messages: prev.messages.filter((m) => m.id !== id) })),
}));
