"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { FaBrain } from "react-icons/fa";

const CHAT_FONT_FAMILY = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";

type Message = {
  role: "user" | "assistant";
  content: string;
};

export default function WidgetPage() {
  const searchParams = useSearchParams();
  const agentId = searchParams.get("agentId");
  const tenantId = searchParams.get("tenantId");
  const bufferRef = useRef("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [wsStatus, setWsStatus] = useState<"connecting" | "open" | "closed" | "error">("closed");
  const [isTyping, setIsTyping] = useState(false);

  const ws = useRef<WebSocket | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

  const connectWs = useCallback(() => {
    if (!agentId) return;

    setWsStatus("connecting");
    const wsUrl = `${process.env.NEXT_PUBLIC_WS_URL}/api/v1/embed/chats/${agentId}/ws?tenant_id=${tenantId}`;
    const socket = new WebSocket(wsUrl);
    ws.current = socket;

    socket.onopen = () => setWsStatus("open");

    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        

        if (data.type === "start") {
          setIsTyping(true);
          return;
        }

        if (data.type === "content" && data.delta) {
          bufferRef.current += data.delta;
          console.log("DELTA:", JSON.stringify(data.delta))
           const cleanedText = bufferRef.current
          .replace(/<think>[\s\S]*?<\/think>/g, "")
          .replace(/\[Source:[^\]]+\]/g, "")
          .replace(/\(Source:[^)]+\)/g, "")
          .trim();
          setIsTyping(false);
          setMessages((prev) => {
            const lastMsg = prev[prev.length - 1];
            if (lastMsg && lastMsg.role === "assistant") {
              return [
                ...prev.slice(0, -1),
                { ...lastMsg, content:cleanedText },
              ];
            } else {
              return [...prev, { role: "assistant", content: cleanedText }];
            }
          });
        }

        if (data.type === "done") {
          setIsTyping(false);
        }
      } catch (err ) {
        setIsTyping(false);
        const text = String(event.data);
        setMessages((prev) => [...prev, { role: "assistant", content: text }]);
      }
    };

    socket.onclose = () => { setWsStatus("closed"); setIsTyping(false); };
    socket.onerror = () => { setWsStatus("error"); setIsTyping(false); };
  }, [agentId, tenantId]);

  useEffect(() => {
    connectWs();
    return () => { ws.current?.close(); };
  }, [connectWs]);

  const handleSend = () => {
    const message = input.trim();
    if (!message) return;
    bufferRef.current = ""; // reset old response
    setMessages((prev) => [...prev, { role: "user", content: message }]);
    setIsTyping(true);
    ws.current?.send(JSON.stringify({ message: message }));
    setInput("");
  };


  return (
    <div
      style={{
        margin: 0,
        padding: 0,
        height: "100vh",
        width: "100%",
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        background: "transparent", 
        fontFamily: CHAT_FONT_FAMILY,
        color: "#222",
      }}
    >
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 0.3; transform: scale(0.8); }
          50% { opacity: 1; transform: scale(1.2); }
        }
        .typing-dot {
          width: 6px;
          height: 6px;
          background-color: #737373;
          border-radius: 50%;
          display: inline-block;
          animation: pulse 1.4s infinite ease-in-out both;
        }
        .typing-dot:nth-child(2) { animation-delay: 0.2s; }
        .typing-dot:nth-child(3) { animation-delay: 0.4s; }
        
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #e5e5e5; border-radius: 10px; }
        ::-webkit-scrollbar-thumb:hover { background: #d4d4d4; }
        .close-btn {
          position: relative;
          width: 16px;
          height: 16px;
          cursor: pointer;
          opacity: 0.6;
          transition: opacity 0.2s;
        }
        .close-btn:hover { opacity: 1; }
        .close-btn::before, .close-btn::after {
          position: absolute;
          left: 7px;
          content: ' ';
          height: 16px;
          width: 1.5px;
          background-color: #555;
        }
        .close-btn::before { transform: rotate(45deg); }
        .close-btn::after { transform: rotate(-45deg); }
      `}</style>

      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          background: "#ffffff",
          borderRadius: "24px", 
          boxShadow: "0 12px 40px rgba(0,0,0,0.12)",
          overflow: "hidden",
          border: "1px solid #e5e5e5"
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: "16px 20px",
            background: "#ffffff",
            borderBottom: "1px solid #f0f0f0",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            {/* <span style={{ cursor: "pointer", color: "#737373", fontSize: "16px" }}>⟨</span> */}
            
            <div style={{
              width: "36px", height: "36px", background: "#000000", borderRadius: "10px",
              display: "flex", alignItems: "center", justifyContent: "center", color: "#ffffff"
            }}>
              <FaBrain size={20} />
            </div>

            <div>
              <div style={{ fontWeight: 600, fontSize: "15px", color: "#171717", display: "flex", alignItems: "center", gap: "6px" }}>
                Gsearch AI
                <span style={{ fontSize: "10px", color: wsStatus === "open" ? "#22c55e" : "#ef4444" }}>●</span>
              </div>
              <div style={{ fontSize: "12px", color: "#737373" }}>
                The team can also help
              </div>
            </div>
          </div>

          {/* Clean Close UI Button */}
          {/* <div style={{ display: "flex", alignItems: "center", paddingRight: "4px" }}>
            <div className="close-btn" onClick={handleClose} />
          </div> */}
        </div>

        {/* Chat Feed */}
        <div
          style={{
            flex: 1,
            overflowY: "auto",
            padding: "20px",
            background: "#f9f9f9", 
            display: "flex",
            flexDirection: "column",
            gap: "16px",
          }}
        >
          {messages.map((msg, index) => {
            const isUser = msg.role === "user";
            return (
              <div
                key={index}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: isUser ? "flex-end" : "flex-start",
                  width: "100%",
                }}
              >
                <div style={{ fontSize: "11px", color: "#a3a3a3", marginBottom: "4px" }}>
                  {isUser ? "You" : "Gsearch • AI Agent"}
                </div>

                <div
                  style={{
                    padding: "12px 16px",
                    borderRadius: "18px",
                    background: isUser ? "#f4f4f5" : "#ffffff", 
                    border: "1px solid #e4e4e7",
                    color: "#18181b",
                    fontSize: "14px",
                    lineHeight: "1.45",
                    maxWidth: "85%",
                    wordBreak: "break-word",
                  }}
                >
                  {msg.content}
                </div>
              </div>
            );
          })}

          {/* Typing Indicator */}
          {isTyping && (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
              <div style={{ fontSize: "11px", color: "#a3a3a3", marginBottom: "4px" }}>Gsearch is typing...</div>
              <div style={{ padding: "12px 16px", borderRadius: "18px", background: "#ffffff", border: "1px solid #e4e4e7", display: "flex", gap: "4px" }}>
                <span className="typing-dot"></span>
                <span className="typing-dot"></span>
                <span className="typing-dot"></span>
              </div>
            </div>
          )}
          
          <div ref={messagesEndRef} />
        </div>

        {/* Input Bar */}
        <div
          style={{
            padding: "16px 20px 20px 20px",
            background: "#ffffff",
            borderTop: "1px solid #f0f0f0",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", background: "#f4f4f5", borderRadius: "24px", padding: "4px 6px 4px 16px" }}>
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleSend(); }}
              placeholder="Ask a question..."
              style={{
                flex: 1,
                padding: "10px 0",
                background: "transparent",
                border: "none",
                color: "#18181b",
                fontSize: "14px",
                outline: "none",
              }}
            />
            
            <button
              onClick={handleSend}
              disabled={!input.trim()}
              style={{
                width: "34px",
                height: "34px",
                background: input.trim() ? "#0066cc" : "#e4e4e7",
                color: input.trim() ? "#ffffff" : "#a3a3a3",
                border: "none",
                borderRadius: "50%",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                cursor: input.trim() ? "pointer" : "default",
                fontSize: "14px",
                fontWeight: "bold",
                transition: "background 0.2s"
              }}
            >
              ↑
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}


// "use client";

// import { useSearchParams } from "next/navigation";
// import { useCallback, useEffect, useRef, useState } from "react";

// // --- Configuration ---
// const CHAT_FONT_FAMILY = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";

// // --- Type Definitions ---
// type Message = {
//   role: "user" | "assistant";
//   content: string;
// };

// export default function WidgetPage() {
//   const searchParams = useSearchParams();
//   const agentId = searchParams.get("agentId");
//   const tenantId = searchParams.get("tenantId");

//   // இமேஜில் உள்ளவாறு ஆரம்ப மெசேஜ்கள் நீக்கப்பட்டு, பழையபடி காலியாக மாற்றப்பட்டுள்ளது
//   const [messages, setMessages] = useState<Message[]>([]);
//   const [input, setInput] = useState("");
//   const [wsStatus, setWsStatus] = useState<"connecting" | "open" | "closed" | "error">("closed");
//   const [isTyping, setIsTyping] = useState(false);

//   const ws = useRef<WebSocket | null>(null);
//   const messagesEndRef = useRef<HTMLDivElement | null>(null);

//   // Auto-scroll to the latest message
//   useEffect(() => {
//     messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
//   }, [messages, isTyping]);

//   const connectWs = useCallback(() => {
//     if (!agentId) return;

//     setWsStatus("connecting");
//     const wsUrl = `ws://192.168.1.158:4915/api/v1/embed/chats/${agentId}/ws?tenant_id=${tenantId}`;
//     const socket = new WebSocket(wsUrl);
//     ws.current = socket;

//     socket.onopen = () => setWsStatus("open");

//     // உங்களது அசல் WebSocket Logic அப்படியே பாதுகாக்கப்பட்டுள்ளது
//     socket.onmessage = (event) => {
//       try {
//         const data = JSON.parse(event.data);

//         // 1. Handle when stream starts
//         if (data.type === "start") {
//           setIsTyping(true);
//           return;
//         }

//         // 2. Handle text chunks
//         if (data.type === "content" && data.delta) {
//           setIsTyping(false); // Hide dots once first real text arrives
//           setMessages((prev) => {
//             const lastMsg = prev[prev.length - 1];
            
//             // If the last message is already from the assistant, append the new text chunk to it
//             if (lastMsg && lastMsg.role === "assistant") {
//               return [
//                 ...prev.slice(0, -1),
//                 { ...lastMsg, content: lastMsg.content + data.delta },
//               ];
//             } else {
//               // Otherwise, create a new assistant message bubble
//               return [...prev, { role: "assistant", content: data.delta }];
//             }
//           });
//         }

//         // 3. Handle stream completion
//         if (data.type === "done") {
//           setIsTyping(false);
//         }
//       } catch (err) {
//         // Fallback for plain string data over WS
//         setIsTyping(false);
//         const text = String(event.data);
//         setMessages((prev) => [...prev, { role: "assistant", content: text }]);
//       }
//     };

//     socket.onclose = () => {
//       setWsStatus("closed");
//       setIsTyping(false);
//     };
//     socket.onerror = () => {
//       setWsStatus("error");
//       setIsTyping(false);
//     };
//   }, [agentId, tenantId]);

//   useEffect(() => {
//     connectWs();
//     return () => {
//       ws.current?.close();
//     };
//   }, [connectWs]);

//   const handleSend = () => {
//     const message = input.trim();
//     if (!message) return;

//     setMessages((prev) => [...prev, { role: "user", content: message }]);
//     setIsTyping(true); // Simulate model thinking
//     ws.current?.send(JSON.stringify({ message: message }));
//     setInput("");
//   };

//   return (
//     <div
//       style={{
//         margin: 0,
//         padding: 0,
//         height: "100vh",
//         width: "100%",
//         display: "flex",
//         justifyContent: "center",
//         alignItems: "center",
//         background: "transparent", 
//         fontFamily: CHAT_FONT_FAMILY,
//         color: "#222",
//       }}
//     >
//       <style>{`
//         @keyframes pulse {
//           0%, 100% { opacity: 0.3; transform: scale(0.8); }
//           50% { opacity: 1; transform: scale(1.2); }
//         }
//         .typing-dot {
//           width: 6px;
//           height: 6px;
//           background-color: #737373;
//           border-radius: 50%;
//           display: inline-block;
//           animation: pulse 1.4s infinite ease-in-out both;
//         }
//         .typing-dot:nth-child(2) { animation-delay: 0.2s; }
//         .typing-dot:nth-child(3) { animation-delay: 0.4s; }
        
//         ::-webkit-scrollbar { width: 6px; }
//         ::-webkit-scrollbar-track { background: transparent; }
//         ::-webkit-scrollbar-thumb { background: #e5e5e5; border-radius: 10px; }
//         ::-webkit-scrollbar-thumb:hover { background: #d4d4d4; }
//       `}</style>

//       {/* Main Container - Light Theme */}
//       <div
//         style={{
//           width: "100%",
//           height: "100%",
//           display: "flex",
//           flexDirection: "column",
//           background: "#ffffff",
//           borderRadius: "24px", 
//           boxShadow: "0 12px 40px rgba(0,0,0,0.12)",
//           overflow: "hidden",
//           border: "1px solid #e5e5e5"
//         }}
//       >
//         {/* Header - Fin AI Agent Style */}
//         <div
//           style={{
//             padding: "16px 20px",
//             background: "#ffffff",
//             borderBottom: "1px solid #f0f0f0",
//             display: "flex",
//             alignItems: "center",
//             justifyContent: "space-between",
//           }}
//         >
//           <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
//             <span style={{ cursor: "pointer", color: "#737373", fontSize: "16px" }}>⟨</span>
            
//             <div style={{
//               width: "32px", height: "32px", background: "#000", borderRadius: "8px",
//               display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontWeight: "bold", fontSize: "14px"
//             }}>
//               ✳
//             </div>

//             <div>
//               <div style={{ fontWeight: 600, fontSize: "15px", color: "#171717" }}>
//                 Fin <span style={{ fontSize: "11px", color: wsStatus === "open" ? "#22c55e" : "#ef4444" }}>●</span>
//               </div>
//               <div style={{ fontSize: "12px", color: "#737373" }}>
//                 The team can also help
//               </div>
//             </div>
//           </div>

//           <div style={{ display: "flex", gap: "14px", color: "#737373", cursor: "pointer", fontSize: "16px" }}>
//             <span>•••</span>
//             <span>✕</span>
//           </div>
//         </div>

//         {/* Chat Feed */}
//         <div
//           style={{
//             flex: 1,
//             overflowY: "auto",
//             padding: "20px",
//             background: "#f9f9f9", 
//             display: "flex",
//             flexDirection: "column",
//             gap: "16px",
//           }}
//         >
//           {messages.map((msg, index) => {
//             const isUser = msg.role === "user";
//             return (
//               <div
//                 key={index}
//                 style={{
//                   display: "flex",
//                   flexDirection: "column",
//                   alignItems: isUser ? "flex-end" : "flex-start",
//                   width: "100%",
//                 }}
//               >
//                 <div style={{ fontSize: "11px", color: "#a3a3a3", marginBottom: "4px" }}>
//                   {isUser ? "You" : "Fin • AI Agent • Just now"}
//                 </div>

//                 <div
//                   style={{
//                     padding: "12px 16px",
//                     borderRadius: "18px",
//                     background: isUser ? "#f4f4f5" : "#ffffff", 
//                     border: "1px solid #e4e4e7",
//                     color: "#18181b",
//                     fontSize: "14px",
//                     lineHeight: "1.45",
//                     maxWidth: "85%",
//                     wordBreak: "break-word",
//                   }}
//                 >
//                   {msg.content}
//                 </div>
//               </div>
//             );
//           })}

//           {/* Typing Indicator */}
//           {isTyping && (
//             <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
//               <div style={{ fontSize: "11px", color: "#a3a3a3", marginBottom: "4px" }}>Fin is typing...</div>
//               <div style={{ padding: "12px 16px", borderRadius: "18px", background: "#ffffff", border: "1px solid #e4e4e7", display: "flex", gap: "4px" }}>
//                 <span className="typing-dot"></span>
//                 <span className="typing-dot"></span>
//                 <span className="typing-dot"></span>
//               </div>
//             </div>
//           )}
          
//           <div ref={messagesEndRef} />
//         </div>

//         {/* Input Bar */}
//         <div
//           style={{
//             padding: "12px 16px",
//             background: "#ffffff",
//             borderTop: "1px solid #f0f0f0",
//             display: "flex",
//             flexDirection: "column",
//             gap: "8px"
//           }}
//         >
//           <div style={{ display: "flex", alignItems: "center", background: "#f4f4f5", borderRadius: "24px", padding: "4px 12px" }}>
//             <input
//               value={input}
//               onChange={(e) => setInput(e.target.value)}
//               onKeyDown={(e) => { if (e.key === "Enter") handleSend(); }}
//               placeholder="Ask a question..."
//               style={{
//                 flex: 1,
//                 padding: "10px 4px",
//                 background: "transparent",
//                 border: "none",
//                 color: "#18181b",
//                 fontSize: "14px",
//                 outline: "none",
//               }}
//             />
            
//             <div style={{ display: "flex", gap: "10px", color: "#a3a3a3", fontSize: "16px", marginRight: "8px", cursor: "pointer" }}>
//               <span>📎</span>
//               <span>😊</span>
//             </div>

//             <button
//               onClick={handleSend}
//               disabled={!input.trim()}
//               style={{
//                 width: "32px",
//                 height: "32px",
//                 background: input.trim() ? "#0066cc" : "#e4e4e7",
//                 color: input.trim() ? "#ffffff" : "#a3a3a3",
//                 border: "none",
//                 borderRadius: "50%",
//                 display: "flex",
//                 alignItems: "center",
//                 justifyContent: "center",
//                 cursor: input.trim() ? "pointer" : "default",
//                 fontSize: "14px",
//                 fontWeight: "bold",
//               }}
//             >
//               ↑
//             </button>
//           </div>
//           <div style={{ fontSize: "10px", color: "#d4d4d4", textAlign: "center", width: "100%" }}>
//             ⚡ Powered by Fin
//           </div>
//         </div>
//       </div>
//     </div>
//   );
// }


// "use client";

// import { useSearchParams } from "next/navigation";
// import { useCallback, useEffect, useRef, useState } from "react";

// type Message = {
//   role: "user" | "assistant";
//   content: string;
// };

// export default function WidgetPage() {
//   // console.error("Widget Page Loaded");
//   const searchParams = useSearchParams();
//   const agentId = searchParams.get("agentId");
//   const tenantId = searchParams.get("tenantId");

//   const [messages, setMessages] = useState<Message[]>([]);
//   const [input, setInput] = useState("");
//   const [wsStatus, setWsStatus] = useState<
//     "connecting" | "open" | "closed" | "error"
//   >("closed");

//   const ws = useRef<WebSocket | null>(null);
//   // console.log(tenantId)
//   const connectWs = useCallback(() => {
//     if (!agentId) return;

//     setWsStatus("connecting");

//     // CHANGE THIS URL IF NEEDED
//     const wsUrl =`ws://192.168.1.158:4915/api/v1/embed/chats/${agentId}/ws?tenant_id=${tenantId}` //`wss://grag.gramopro.ai/api/v1/rag/ws/${agentId}`;

//     const socket = new WebSocket(wsUrl);

//     ws.current = socket;

//     socket.onopen = () => {
//       console.log("WebSocket Opened");
//       setWsStatus("open");
//     };

//     socket.onmessage = (event) => {
//       const text = String(event.data);

//       setMessages((prev) => [
//         ...prev,
//         {
//           role: "assistant",
//           content: text,
//         },
//       ]);
//     };

//     socket.onclose = () => {
//       console.log("WebSocket Closed");
//       setWsStatus("closed");
//     };

//     socket.onerror = () => {
//       console.log("WebSocket Error");
//       setWsStatus("error");
//     };
//   }, [agentId , tenantId]);

//   useEffect(() => {
//     connectWs();

//     return () => {
//       ws.current?.close();
//     };
//   }, [connectWs]);

//   const handleSend = () => {
//     const message = input.trim();

//     if (!message) return;

//     setMessages((prev) => [
//       ...prev,
//       {
//         role: "user",
//         content: message,
//       },
//     ]);

//     ws.current?.send(
//       JSON.stringify({
//         message: message,
//       })
//     );

//     setInput("");
//   };

//   return (
//     <div
//       style={{
//         height: "100vh",
//         display: "flex",
//         flexDirection: "column",
//         background: "#fff",
//       }}
//     >
//       {/* Header */}
//       <div
//         style={{
//           padding: "12px",
//           borderBottom: "1px solid #ddd",
//           fontWeight: 600,
//         }}
//       >
//         AI Assistant
//         <div
//           style={{
//             fontSize: "12px",
//             color: "#666",
//           }}
//         >
//           Status: {wsStatus}
//         </div>
//       </div>

//       {/* Messages */}
//       <div
//         style={{
//           flex: 1,
//           overflowY: "auto",
//           padding: "12px",
//         }}
//       >
//         {messages.map((msg, index) => (
//           <div
//             key={index}
//             style={{
//               display: "flex",
//               justifyContent:
//                 msg.role === "user"
//                   ? "flex-end"
//                   : "flex-start",
//               marginBottom: "10px",
//             }}
//           >
//             <div
//               style={{
//                 maxWidth: "80%",
//                 padding: "10px",
//                 borderRadius: "10px",
//                 background:
//                   msg.role === "user"
//                     ? "#1677ff"
//                     : "#f3f3f3",
//                 color:
//                   msg.role === "user"
//                     ? "#fff"
//                     : "#000",
//               }}
//             >
//               {msg.content}
//             </div>
//           </div>
//         ))}
//       </div>

//       {/* Input */}
//       <div
//         style={{
//           padding: "12px",
//           borderTop: "1px solid #ddd",
//           display: "flex",
//           gap: "10px",
//         }}
//       >
//         <input
//           value={input}
//           onChange={(e) =>
//             setInput(e.target.value)
//           }
//           onKeyDown={(e) => {
//             if (e.key === "Enter") {
//               handleSend();
//             }
//           }}
//           placeholder="Type a message..."
//           style={{
//             flex: 1,
//             padding: "10px",
//             border: "1px solid #ccc",
//             borderRadius: "8px",
//           }}
//         />

//         <button
//           onClick={handleSend}
//           style={{
//             padding: "10px 16px",
//             border: "none",
//             borderRadius: "8px",
//             cursor: "pointer",
//           }}
//         >
//           Send
//         </button>
//       </div>
//     </div>
//   );
// }

// "use client";

// import { useSearchParams } from "next/navigation";
// import { useCallback, useEffect, useRef, useState } from "react";

// type Message = {
//   role: "user" | "assistant";
//   content: string;
// };

// export default function WidgetPage() {
//   const searchParams = useSearchParams();
//   const agentId = searchParams.get("agentId");
//   const tenantId = searchParams.get("tenantId");

//   const [messages, setMessages] = useState<Message[]>([]);
//   const [input, setInput] = useState("");
//   const [wsStatus, setWsStatus] = useState<"connecting" | "open" | "closed" | "error">("closed");
//   const [isTyping, setIsTyping] = useState(false);

//   const ws = useRef<WebSocket | null>(null);
//   const messagesEndRef = useRef<HTMLDivElement | null>(null);

//   // Auto-scroll to the latest message
//   useEffect(() => {
//     messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
//   }, [messages, isTyping]);

//   const connectWs = useCallback(() => {
//     if (!agentId) return;

//     setWsStatus("connecting");
//     const wsUrl = `ws://192.168.1.158:4915/api/v1/embed/chats/${agentId}/ws?tenant_id=${tenantId}`;
//     const socket = new WebSocket(wsUrl);
//     ws.current = socket;

//     socket.onopen = () => setWsStatus("open");

//     socket.onmessage = (event) => {
//       try {
//         const data = JSON.parse(event.data);

//         // 1. Handle when stream starts
//         if (data.type === "start") {
//           setIsTyping(true);
//           return;
//         }

//         // 2. Handle text chunks (Fixes the duplication bug!)
//         if (data.type === "content" && data.delta) {
//           setIsTyping(false); // Hide generic typing dots once content arrives
//           setMessages((prev) => {
//             const lastMsg = prev[prev.length - 1];
            
//             // If the last message is already from the assistant, append the new text chunk to it
//             if (lastMsg && lastMsg.role === "assistant") {
//               return [
//                 ...prev.slice(0, -1),
//                 { ...lastMsg, content: lastMsg.content + data.delta },
//               ];
//             } else {
//               // Otherwise, create a new assistant message bubble
//               return [...prev, { role: "assistant", content: data.delta }];
//             }
//           });
//         }

//         // 3. Handle stream completion
//         if (data.type === "done") {
//           setIsTyping(false);
//         }
//       } catch (err) {
//         // Fallback for plain string data over WS
//         setIsTyping(false);
//         const text = String(event.data);
//         setMessages((prev) => [...prev, { role: "assistant", content: text }]);
//       }
//     };

//     socket.onclose = () => {
//       setWsStatus("closed");
//       setIsTyping(false);
//     };
//     socket.onerror = () => {
//       setWsStatus("error");
//       setIsTyping(false);
//     };
//   }, [agentId, tenantId]);

//   useEffect(() => {
//     connectWs();
//     return () => {
//       ws.current?.close();
//     };
//   }, [connectWs]);

//   const handleSend = () => {
//     const message = input.trim();
//     if (!message) return;

//     setMessages((prev) => [...prev, { role: "user", content: message }]);
    
//     // Simulate typing right after user hits send until server responds
//     setIsTyping(true); 

//     ws.current?.send(JSON.stringify({ message: message }));
//     setInput("");
//   };

//   return (
//     <div
//       style={{
//         height: "100vh",
//         display: "flex",
//         flexDirection: "column",
//         background: "#121115", // Premium sleek dark layout background
//         fontFamily: "Inter, -apple-system, BlinkMacSystemFont, sans-serif",
//         color: "#fff",
//       }}
//     >
//       {/* Dynamic Style Injection for Typing Animation & Scrollbar */}
//       <style>{`
//         @keyframes pulse {
//           0%, 100% { opacity: 0.3; transform: scale(0.8); }
//           50% { opacity: 1; transform: scale(1.2); }
//         }
//         .typing-dot {
//           width: 8px;
//           height: 8px;
//           background-color: #a5a2b0;
//           border-radius: 50%;
//           display: inline-block;
//           animation: pulse 1.4s infinite ease-in-out both;
//         }
//         .typing-dot:nth-child(2) { animation-delay: 0.2s; }
//         .typing-dot:nth-child(3) { animation-delay: 0.4s; }
        
//         /* Smooth Custom Scrollbar */
//         ::-webkit-scrollbar { width: 6px; }
//         ::-webkit-scrollbar-track { background: transparent; }
//         ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 10px; }
//         ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.2); }
//       `}</style>

//       {/* Header - Cleaned up without extra phone icons */}
//       <div
//         style={{
//           padding: "16px 24px",
//           background: "#18161c",
//           borderBottom: "1px solid rgba(255, 255, 255, 0.05)",
//           display: "flex",
//           alignItems: "center",
//           justifyContent: "space-between"
//         }}
//       >
//         <div>
//           <div style={{ fontWeight: 600, fontSize: "15px", color: "#f5f5f7", letterSpacing: "0.3px" }}>
//             AI Astrologer
//           </div>
//           <div style={{ fontSize: "11px", color: "rgba(255,255,255,0.4)", marginTop: "2px" }}>
//             {wsStatus === "open" ? "● Online" : "○ Disconnected"}
//           </div>
//         </div>
//       </div>

//       {/* Chat Messages Feed */}
//       <div
//         style={{
//           flex: 1,
//           overflowY: "auto",
//           padding: "24px 20px",
//           display: "flex",
//           flexDirection: "column",
//           gap: "20px",
//         }}
//       >
//         {messages.map((msg, index) => {
//           const isUser = msg.role === "user";
//           return (
//             <div
//               key={index}
//               style={{
//                 display: "flex",
//                 justifyContent: isUser ? "flex-end" : "flex-start",
//                 alignItems: "flex-end",
//                 gap: "10px",
//                 width: "100%",
//               }}
//             >
//               {/* Profile Avatar for AI */}
//               {!isUser && (
//                 <div
//                   style={{
//                     width: "32px",
//                     height: "32px",
//                     borderRadius: "50%",
//                     background: "#242129",
//                     border: "1px solid rgba(255,255,255,0.08)",
//                     display: "flex",
//                     alignItems: "center",
//                     justifyContent: "center",
//                     fontSize: "15px",
//                     boxShadow: "0 4px 10px rgba(0,0,0,0.2)"
//                   }}
//                 >
//                   🔮
//                 </div>
//               )}

//               {/* Chat Bubble Layout matched to your screenshot */}
//               <div
//                 style={{
//                   padding: "14px 18px",
//                   borderRadius: isUser ? "20px 20px 4px 20px" : "20px 20px 20px 4px",
//                   background: isUser ? "#29272e" : "#20283e", // Sleek gray for User, Beautiful deep navy blue for AI
//                   border: isUser ? "1px solid rgba(255,255,255,0.06)" : "1px solid rgba(255,255,255,0.1)",
//                   color: "#e2e1e6",
//                   fontSize: "14.5px",
//                   lineHeight: "1.5",
//                   maxWidth: "75%",
//                   wordBreak: "break-word",
//                   boxShadow: "0 2px 8px rgba(0,0,0,0.15)"
//                 }}
//               >
//                 {msg.content}
//               </div>
//             </div>
//           );
//         })}

//         {/* Beautiful Animated Wave Typing Indicator */}
//         {isTyping && (
//           <div style={{ display: "flex", alignItems: "flex-end", gap: "10px" }}>
//             <div style={{
//               width: "32px", height: "32px", borderRadius: "50%", background: "#242129",
//               display: "flex", alignItems: "center", justifyContent: "center", fontSize: "15px"
//             }}>
//               🔮
//             </div>
//             <div
//               style={{
//                 padding: "14px 20px",
//                 borderRadius: "20px 20px 20px 4px",
//                 background: "#20283e",
//                 display: "flex",
//                 alignItems: "center",
//                 gap: "5px",
//                 boxShadow: "0 2px 8px rgba(0,0,0,0.15)"
//               }}
//             >
//               <span className="typing-dot"></span>
//               <span className="typing-dot"></span>
//               <span className="typing-dot"></span>
//             </div>
//           </div>
//         )}
        
//         <div ref={messagesEndRef} />
//       </div>

//       {/* Input Console */}
//       <div
//         style={{
//           padding: "16px 20px",
//           background: "#18161c",
//           borderTop: "1px solid rgba(255, 255, 255, 0.05)",
//           display: "flex",
//           gap: "12px",
//           alignItems: "center",
//         }}
//       >
//         <input
//           value={input}
//           onChange={(e) => setInput(e.target.value)}
//           onKeyDown={(e) => {
//             if (e.key === "Enter") handleSend();
//           }}
//           placeholder="Type your message..."
//           style={{
//             flex: 1,
//             padding: "14px 20px",
//             background: "#111013",
//             border: "1px solid rgba(255, 255, 255, 0.08)",
//             borderRadius: "24px",
//             color: "#fff",
//             fontSize: "14px",
//             outline: "none",
//           }}
//         />

//         <button
//           onClick={handleSend}
//           style={{
//             padding: "12px 22px",
//             background: "linear-gradient(135deg, #2b3a60 0%, #1c2744 100%)",
//             color: "#e2e1e6",
//             border: "1px solid rgba(255,255,255,0.1)",
//             borderRadius: "24px",
//             fontWeight: "600",
//             fontSize: "13.5px",
//             cursor: "pointer",
//             boxShadow: "0 4px 12px rgba(0,0,0,0.2)",
//           }}
//         >
//           Send
//         </button>
//       </div>
//     </div>
//   );
// }