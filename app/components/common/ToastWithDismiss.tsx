"use client";

import { Toaster, ToastBar, toast } from "react-hot-toast";

export default function ToastWithDismiss() {
  return (
    <Toaster
      position="top-right"
      toastOptions={{
        duration: 5000,
      }}
    >
      {(t) => (
        <ToastBar toast={t}>
          {({ icon, message }) => (
            <>
              {icon}
              {message}
              {t.type !== "loading" && (
                <button
                  type="button"
                  onClick={() => toast.dismiss(t.id)}
                  className="ml-2 inline-flex items-center justify-center rounded-md p-1 text-gray-400 hover:text-gray-700 hover:bg-gray-100 dark:hover:bg-gray-700 dark:hover:text-gray-200 transition-colors"
                  title="Close"
                  aria-label="Close"
                >
                  ✕
                </button>
              )}
            </>
          )}
        </ToastBar>
      )}
    </Toaster>
  );
}
