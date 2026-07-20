
(function () {
  const script = document.currentScript;
   if (!script) return;
  const agentId = script.getAttribute("data-agent-id");
  const tenantId = script.getAttribute("data-tenant-id");
  const chatType = script.getAttribute("data-chat-type") || "icon"; // "icon" or "search"
  const position = script.getAttribute("data-position") || "center"; // "center" or "right"
  const placeholder = script.getAttribute("data-placeholder") || "Ask about anything...";
  const themeColor = script.getAttribute("data-theme-color") || "#0fb5a1";
  // Dynamically detect base URL of the hosting widget
  let baseUrl = "http://grag.gramopro.ai";
  try {
    const scriptSrc = script.getAttribute("src");
    if (scriptSrc && scriptSrc.startsWith("http")) {
      const url = new URL(scriptSrc);
      baseUrl = url.origin;
    } else {
      baseUrl = window.location.origin;
    }
  } catch (e) {
    console.error("GragWidget: Error parsing script URL, falling back.", e);
  }
  // --- Common Style Elements (Keyframes & Animations) ---
  const styleEl = document.createElement("style");
  styleEl.innerHTML = `
    .grag-iframe-container {
      position: fixed;
      display: none;
      border: none;
      background: transparent;
      border-radius: 24px;
      box-shadow: 0 12px 32px rgba(0, 0, 0, 0.15);
      z-index: 999999;
      opacity: 0;
      transform: translateY(20px);
      transition: opacity 0.3s cubic-bezier(0.16, 1, 0.3, 1), transform 0.3s cubic-bezier(0.16, 1, 0.3, 1);
    }
    .grag-iframe-container.show {
      display: block;
      opacity: 1;
      transform: translateY(0);
    }
  `;
  document.head.appendChild(styleEl);

  // Create Iframe element
  const iframe = document.createElement("iframe");
  iframe.className = "grag-iframe-container";
  iframe.style.border = "none";
  iframe.style.background = "transparent";
  iframe.style.borderRadius = "24px";
  iframe.style.boxShadow = "0 12px 32px rgba(0, 0, 0, 0.15)";
  iframe.style.zIndex = "999999";
  iframe.src = `${baseUrl}/widget?agentId=${agentId}&tenantId=${tenantId}&chatType=${chatType}&themeColor=${encodeURIComponent(themeColor)}`;
  
  // Declared search wrapper reference
  let searchWrapper = null;
  
  // Global window resize and responsive dimensions
  const updateIframeDimensions = () => {
    const isMobile = window.innerWidth <= 640;
    if (isMobile) {
      iframe.style.width = "100%";
      iframe.style.height = "100%";
      iframe.style.bottom = "0";
      iframe.style.right = "0";
      iframe.style.left = "0";
      iframe.style.borderRadius = "0";
    } else {
      iframe.style.borderRadius = "24px";
      if (chatType === "search") {
        if (position === "center") {
          iframe.style.width = "680px";
          iframe.style.height = "520px";
          iframe.style.bottom = "30px"; // Position directly at bottom when search bar gets hidden
          iframe.style.left = "50%";
          iframe.style.right = "auto";
          iframe.style.transform = iframe.classList.contains("show")
            ? "translateX(-50%) translateY(0)"
            : "translateX(-50%) translateY(20px)";
        } else {
          // right
          iframe.style.width = "420px";
          iframe.style.height = "520px";
          iframe.style.bottom = "30px"
          iframe.style.right = "40px";
          iframe.style.left = "auto";
        }
      } else {
        // icon style
        iframe.style.width = "420px";
        iframe.style.height = "520px";
        iframe.style.bottom = "95px";
        iframe.style.right = "20px";
        iframe.style.left = "auto";
      }
    }
  };
  window.addEventListener("resize", updateIframeDimensions);
  // Set initial position layout for iframe
  updateIframeDimensions();

  document.body.appendChild(iframe);
  const openIframe = (initialQuery = "") => {
    let src = `${baseUrl}/widget?agentId=${agentId}&tenantId=${tenantId}&chatType=${chatType}&themeColor=${encodeURIComponent(themeColor)}`;
    if (initialQuery) {
      src += `&q=${encodeURIComponent(initialQuery)}`;

    }
    iframe.src = src;
    iframe.style.display = "block";

    // Hide search bar wrapper to prevent double input boxes
    if (chatType === "search" && searchWrapper) {
      searchWrapper.style.display = "none";
    }
    
    // Tiny delay to ensure display:block is registered before adding transition class
    setTimeout(() => {
      iframe.classList.add("show");
      if (chatType === "search" && position === "center" && window.innerWidth > 640) {
        iframe.style.transform = "translateX(-50%) translateY(0)";
      }
    }, 20);
  };
const closeIframe = () => {
    iframe.classList.remove("show");
    if (chatType === "search" && position === "center" && window.innerWidth > 640) {
      iframe.style.transform = "translateX(-50%) translateY(20px)";
    }

     // Show search bar wrapper back
    if (chatType === "search" && searchWrapper) {
      searchWrapper.style.display = "block";
    }
    setTimeout(() => {
      if (!iframe.classList.contains("show")) {
        iframe.style.display = "none";
      }
    }, 300);
  };
  // Listen to postMessage from the iframe widget to close/collapse the chat window
  window.addEventListener("message", (event) => {
    if (event.data && event.data.type === "close-chat") {
      closeIframe();
    }
  });
  if (chatType === "search") {
    // --- Style 2: Search Bar Style Chat ---
    // Create wrapper container to manage margins and positioning on the host site
    searchWrapper = document.createElement("div");
    searchWrapper.style.position = "fixed";
    searchWrapper.style.zIndex = "999998";
    searchWrapper.style.boxSizing = "border-box";
    searchWrapper.style.fontFamily = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
    if (position === "center") {
      searchWrapper.style.bottom = "30px";
      searchWrapper.style.left = "50%";
      searchWrapper.style.transform = "translateX(-50%)";
      searchWrapper.style.width = "90%";
      searchWrapper.style.maxWidth = "680px";
    } else {
      // right
      searchWrapper.style.bottom = "30px";
      searchWrapper.style.right = "40px";
      searchWrapper.style.width = "90%";
      searchWrapper.style.maxWidth = "420px";
    }
     // Outer glow container (which handles brand gradient outline on focus/hover)
    const glowContainer = document.createElement("div");
    glowContainer.style.padding = "2px";
    glowContainer.style.borderRadius = "26px";
    glowContainer.style.background = "#e4e4e7"; // slate border by default
    glowContainer.style.transition = "background 0.3s ease, box-shadow 0.3s ease";
    glowContainer.style.boxShadow = "0 8px 24px rgba(0, 0, 0, 0.08)";
    // Inner input bar container
    const inputBar = document.createElement("div");
    inputBar.style.display = "flex";
    inputBar.style.alignItems = "center";
    inputBar.style.background = "#ffffff";
    inputBar.style.borderRadius = "24px";
    inputBar.style.padding = "6px 8px 6px 18px";
    inputBar.style.gap = "12px";
    inputBar.style.boxSizing = "border-box";
    // Left Icon (Clock/History SVG)
    const leftIcon = document.createElement("span");
    leftIcon.style.display = "flex";
    leftIcon.style.alignItems = "center";
    leftIcon.style.color = "#71717a";
    leftIcon.style.cursor = "pointer";
    leftIcon.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"/>
        <polyline points="12 6 12 12 16 14"/>
      </svg>
    `;
    // Input Element
    const input = document.createElement("input");
    input.type = "text";
    input.placeholder = placeholder;
    input.style.flex = "1";
    input.style.border = "none";
    input.style.outline = "none";
    input.style.background = "transparent";
    input.style.color = "#18181b";
    input.style.fontSize = "15px";
    input.style.fontFamily = "inherit";
    input.style.padding = "8px 0";
    // Right Send Button
    const sendBtn = document.createElement("button");
    sendBtn.style.width = "34px";
    sendBtn.style.height = "34px";
    sendBtn.style.borderRadius = "50%";
    sendBtn.style.background = "#f4f4f5"; // grey default
    sendBtn.style.border = "none";
    sendBtn.style.cursor = "pointer";
    sendBtn.style.display = "flex";
    sendBtn.style.alignItems = "center";
    sendBtn.style.justifyContent = "center";
    sendBtn.style.transition = "background-color 0.2s ease, transform 0.2s ease";
    sendBtn.style.color = "#a1a1aa";
    sendBtn.disabled = true;
    sendBtn.innerHTML = `
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <line x1="12" y1="19" x2="12" y2="5"/>
        <polyline points="5 12 12 5 19 12"/>
      </svg>
    `;
    // Interactivity logic: Change glow & send button color on input focus/type
    input.onfocus = () => {
      glowContainer.style.background = themeColor;
      glowContainer.style.boxShadow = `0 8px 30px ${themeColor}30`;
    };
    input.onblur = () => {
      glowContainer.style.background = "#e4e4e7";
      glowContainer.style.boxShadow = "0 8px 24px rgba(0, 0, 0, 0.08)";
    };
    input.oninput = (e) => {
      const val = e.target.value.trim();
      if (val.length > 0) {
        sendBtn.style.background = themeColor;
        sendBtn.style.color = "#ffffff";
        sendBtn.disabled = false;
      } else {
        sendBtn.style.background = "#f4f4f5";
        sendBtn.style.color = "#a1a1aa";
        sendBtn.disabled = true;
      }
    };
    const handleSearchSubmit = () => {
      const query = input.value.trim();
      if (!query) return;
      openIframe(query);
      input.value = "";
      sendBtn.style.background = "#f4f4f5";
      sendBtn.style.color = "#a1a1aa";
      sendBtn.disabled = true;
    };
    input.onkeydown = (e) => {
      if (e.key === "Enter") {
        handleSearchSubmit();
      }
    };
    sendBtn.onclick = handleSearchSubmit;
    leftIcon.onclick = () => {
      openIframe("");
    };
    // Assemble and render elements
    inputBar.appendChild(leftIcon);
    inputBar.appendChild(input);
    inputBar.appendChild(sendBtn);
    glowContainer.appendChild(inputBar);
    searchWrapper.appendChild(glowContainer);
    document.body.appendChild(searchWrapper);
  } else {
    // --- Style 1: Classic Icon Style Chat (Current Style) ---
    const button = document.createElement("button");
    button.innerHTML = `
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M21 11.5C21 16.7467 16.9706 21 12 21C10.1302 21 8.39632 20.3992 6.97743 19.3722L3 20.5L4.15064 16.6329C3.41732 15.1543 3 13.4754 3 11.5C3 6.25329 7.02944 2 12 2C16.9706 2 21 6.25329 21 11.5Z" fill="${themeColor}" stroke="${themeColor}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M8 10H16M8 14H14" stroke="white" stroke-width="2" stroke-linecap="round"/>
      </svg>
    `;
    button.style.position = "fixed";
    button.style.bottom = "20px";
    button.style.right = "20px";
    button.style.width = "60px";
    button.style.height = "60px";
    button.style.borderRadius = "50%";
    button.style.cursor = "pointer";
    button.style.background = "#ffffff";
    button.style.border = "1px solid #e5e5e5";
    button.style.boxShadow = "0 4px 16px rgba(0, 0, 0, 0.15)";
    button.style.display = "flex";
    button.style.alignItems = "center";
    button.style.justifyContent = "center";
    button.style.zIndex = "999999";
    button.style.transition = "transform 0.2s ease";
    button.onmouseover = () => button.style.transform = "scale(1.05)";
    button.onmouseout = () => button.style.transform = "scale(1)";
    document.body.appendChild(button);
    // Toggle click trigger
    button.onclick = () => {
      if (iframe.classList.contains("show")) {
        closeIframe();
      } else {
        openIframe();
      }
    };
  }
})();