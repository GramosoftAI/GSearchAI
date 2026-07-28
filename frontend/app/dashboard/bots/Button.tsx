import { useState } from "react";

export default function IframePopup() {
  const [open, setOpen] = useState(false);

  return (
    <div>
      {/* Round Button */}
      <button
        onClick={() => setOpen(true)}
        style={{
          width: "60px",
          height: "60px",
          borderRadius: "50%",
          background: "#007bff",
          color: "white",
          border: "none",
          fontSize: "24px",
          cursor: "pointer",
          position: "fixed",
          bottom: "20px",
          right: "20px",
        }}
      >
        +
      </button>

      {/* Modal */}
      {open && (
        <div
          onClick={() => setOpen(false)}
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            width: "100%",
            height: "100%",
            background: "rgba(0,0,0,0.7)",
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
          }}
        >
          {/* Prevent close when clicking inside iframe box */}
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: "50%",
              height: "50%",
              background: "white",
              position: "relative",
              left:"0%",
              zIndex:1
            }}
          >
            {/* Close button */}
            <button
              onClick={() => setOpen(false)}
              style={{
                position: "absolute",
                right: "10px",
                top: "10px",
                border: "none",
                background: "red",
                color: "white",
                fontSize: "18px",
                cursor: "pointer",
              }}
            >
              ✕
            </button>

            {/* Iframe */}
            <iframe
              src="https://dashboard/conversation"
              style={{ width: "100%", height: "100%", border: "none" }}
            />
          </div>
        </div>
      )}
    </div>
  );
}