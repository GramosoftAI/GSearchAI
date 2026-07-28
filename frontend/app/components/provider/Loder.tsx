"use client";

export const Loader = () => {
  return (
    <div className="loader-overlay">
      <div className="loader-content">
        <div className="textWrapper">
          <p className="text">Loading...</p>
          <div className="invertbox" />
        </div>
        <div className="neural-pulses">
          <div className="pulse" />
          <div className="pulse" style={{ animationDelay: '0.5s' }} />
        </div>
      </div>

      <style jsx>{`
        .loader-overlay {
          position: fixed;
          inset: 0;
          display: flex;
          align-items: center;
          justify-content: center;
          background-color: transparent;
          backdrop-filter: blur(8px) saturate(150%);
          z-index: 9999;
        }

        .loader-content {
          position: relative;
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 1.5rem;
        }

        .textWrapper {
          height: fit-content;
          min-width: 2rem;
          width: fit-content;
          font-size: 1.5rem;
          font-weight: 900;
          letter-spacing: 0.2ch;
          position: relative;
          z-index: 10;
          color: var(--app-text);
          filter: drop-shadow(0 0 10px rgba(40, 93, 145, 0.1));
        }

        .text {
          margin: 0;
          text-transform: uppercase;
        }

        .invertbox {
          position: absolute;
          height: 100%;
          aspect-ratio: 1/1;
          left: 0;
          top: 0;
          border-radius: 24%;
          background-color: #ffffffff;
          mix-blend-mode: difference;
          animation: move 2.5s cubic-bezier(0.65, 0, 0.35, 1) infinite;
        }

        .neural-pulses {
          position: absolute;
          width: 100%;
          height: 100%;
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 0;
        }

        .pulse {
          position: absolute;
          width: 100px;
          height: 100px;
          border-radius: 50%;
          border: 1px solid #ffffffff;
          opacity: 0;
          animation: pulse-out 3s ease-out infinite;
        }

        @keyframes pulse-out {
          0% { transform: scale(0.8); opacity: 0; }
          50% { opacity: 0.15; }
          100% { transform: scale(2); opacity: 0; }
        }

        @keyframes move {
          0%, 100% { left: -10%; }
          50% { left: 110%; transform: translateX(-100%); }
        }

        @media (max-width: 640px) {
          .textWrapper {
            font-size: 1.25rem;
          }
          .pulse {
            width: 80px;
            height: 80px;
          }
        }
      `}</style>
    </div>
  );
}

export default Loader;