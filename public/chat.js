(function () {
  const script = document.currentScript;
  if (!script) return;
  const agentId = script.getAttribute("data-agent-id");
  const tenantId = script.getAttribute("data-tenant-id");
  const chatType = script.getAttribute("data-chat-type") || "icon"; // "icon" or "search"
  const position = script.getAttribute("data-position") || "center"; // "center" or "right"
  const placeholder = script.getAttribute("data-placeholder") || "Ask about anything...";
  const themeColor = script.getAttribute("data-theme-color") || "#0fb5a1";

  // Custom design & branding attributes
  const headerLogo = script.getAttribute("data-header-logo") || "";
  const headerAlign = script.getAttribute("data-header-align") || "center";
  const botAvatar = script.getAttribute("data-bot-avatar") || "";
  const buttonIcon = script.getAttribute("data-button-icon") || "";
  const buttonAlign = script.getAttribute("data-button-align") || "right";
  const showButtonText = script.getAttribute("data-show-button-text") === "true";
  const buttonText = script.getAttribute("data-button-text") || "";
  const initialMessage = script.getAttribute("data-initial-message") || "";
  const displaySources = script.getAttribute("data-display-sources") || "true";
  const allowDownloads = script.getAttribute("data-allow-downloads") || "false";
  const displayCopy = script.getAttribute("data-display-copy") || "true";
  const displayFeedback = script.getAttribute("data-display-feedback") || "true";
  const linkSafety = script.getAttribute("data-link-safety") || "false";

  // Lead Collection & Support Escalation Attributes
  const leadCollection = script.getAttribute("data-lead-collection") || "false";
  const leadFields = script.getAttribute("data-lead-fields") || "";
  const leadTiming = script.getAttribute("data-lead-timing") || "pre-chat";
  const escalationEnabled = script.getAttribute("data-escalation-enabled") || "false";
  const escalationLink = script.getAttribute("data-escalation-link") || "";

  // Dynamically detect base URL of the hosting widget
  let baseUrl = "";
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

  // --- Style Elements (Keyframes & Animations) ---
  const styleEl = document.createElement("style");
  styleEl.innerHTML = `
    .grag-iframe-container {
      position: fixed !important;
      border: none !important;
      background: transparent !important;
      border-radius: 24px;
      z-index: 2147483647 !important;
      opacity: 0;
      visibility: hidden;
      transform: translateY(30px);
      transition: opacity 0.35s cubic-bezier(0.16, 1, 0.3, 1), transform 0.35s cubic-bezier(0.16, 1, 0.3, 1), visibility 0.35s;
      will-change: transform, opacity;
      isolation: isolate;
    }
    .grag-iframe-container.show {
      visibility: visible;
      opacity: 1;
      transform: translateY(0);
    }
    @media (min-width: 641px) {
      .grag-iframe-container.center-search {
        transform: translateX(-50%) translateY(30px);
      }
      .grag-iframe-container.center-search.show {
        transform: translateX(-50%) translateY(0);
      }
    }
    .grag-search-glow {
      padding: 2px;
      border-radius: 26px;
      background: linear-gradient(90deg, ${themeColor}, ${themeColor}ee, #ffffff, ${themeColor}ee, ${themeColor});
      background-size: 300% 100%;
      animation: borderShift 3s ease infinite;
      box-shadow: 0 4px 16px ${themeColor}30;
      transition: box-shadow 0.3s ease;
    }
    .grag-search-glow.active, .grag-search-glow:hover {
      box-shadow: 0 6px 24px ${themeColor}50;
    }
    @keyframes borderShift {
      0% { background-position: 0% 50%; }
      50% { background-position: 100% 50%; }
      100% { background-position: 0% 50%; }
    }
    .grag-icon-btn {
      position: fixed;
      bottom: 20px;
      ${buttonAlign === "left" ? "left: 20px; right: auto;" : "right: 20px; left: auto;"}
      min-width: 60px;
      height: 60px;
      border-radius: 50%;
      cursor: pointer;
      background: #ffffff;
      border: 2px solid ${themeColor};
      box-shadow: 0 6px 20px ${themeColor}40;
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 999999;
      transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275), box-shadow 0.3s ease;
      animation: floatPulse 3s ease-in-out infinite;
    }
    .grag-icon-btn:hover {
      transform: scale(1.05) !important;
      box-shadow: 0 10px 30px ${themeColor}65;
    }
    @keyframes floatPulse {
      0%, 100% {
        transform: translateY(0) scale(1);
        box-shadow: 0 6px 20px ${themeColor}40;
      }
      50% {
        transform: translateY(-7px) scale(1.05);
        box-shadow: 0 12px 28px ${themeColor}60;
      }
    }
    .grag-search-glow button {
      width: 34px;
      height: 34px;
    }
    @media (max-width: 640px) {
      .grag-search-glow button {
        width: 30px !important;
        height: 30px !important;
      }
    }
  `;
  document.head.appendChild(styleEl);

  // Create Iframe element
  const iframe = document.createElement("iframe");
  iframe.className = "grag-iframe-container";
  if (chatType === "search" && position === "center") {
    iframe.classList.add("center-search");
  }
  iframe.style.border = "none";
  iframe.style.background = "transparent";
  iframe.style.borderRadius = "24px";
  iframe.style.zIndex = "2147483647";
  iframe.setAttribute("allowtransparency", "true");
  iframe.src = `${baseUrl}/widget?agentId=${agentId}&tenantId=${tenantId}&chatType=${chatType}&themeColor=${encodeURIComponent(themeColor)}&headerLogo=${encodeURIComponent(headerLogo)}&headerAlign=${encodeURIComponent(headerAlign)}&botAvatar=${encodeURIComponent(botAvatar)}&buttonIcon=${encodeURIComponent(buttonIcon)}&buttonAlign=${encodeURIComponent(buttonAlign)}&showButtonText=${showButtonText}&buttonText=${encodeURIComponent(buttonText)}&initialMessage=${encodeURIComponent(initialMessage)}&displaySources=${displaySources}&allowDownloads=${allowDownloads}&displayCopy=${displayCopy}&displayFeedback=${displayFeedback}&linkSafety=${linkSafety}&leadCollection=${leadCollection}&leadFields=${encodeURIComponent(leadFields)}&leadTiming=${leadTiming}&escalationEnabled=${escalationEnabled}&escalationLink=${encodeURIComponent(escalationLink)}`;


  // Declared search wrapper reference
  let searchWrapper = null;

  // Global window resize and responsive dimensions
  const updateIframeDimensions = () => {
    const isMobile = window.innerWidth <= 640;
    if (isMobile) {
      iframe.style.width = "calc(100% - 32px)";
      iframe.style.height = "calc(100% - 40px)";
      iframe.style.top = "20px";
      iframe.style.bottom = "20px";
      iframe.style.right = "16px";
      iframe.style.left = "16px";
      iframe.style.borderRadius = "24px";
    } else {
      iframe.style.top = "auto";
      iframe.style.borderRadius = "24px";
      if (chatType === "search") {
        if (position === "center") {
          const safeHeight = Math.min(520, window.innerHeight - 60);
          iframe.style.width = "680px";
          iframe.style.height = safeHeight + "px";
          iframe.style.bottom = "30px";
          iframe.style.left = "50%";
          iframe.style.right = "auto";
        } else {
          // right search
          const safeHeight = Math.min(520, window.innerHeight - 60);
          iframe.style.width = "420px";
          iframe.style.height = safeHeight + "px";
          iframe.style.bottom = "30px";
          iframe.style.right = "40px";
          iframe.style.left = "auto";
        }
      } else {
        // icon style - bottom: 95px so safe height = viewport - 95 - 20 top margin
        const bottomOffset = 95;
        const safeHeight = Math.min(520, window.innerHeight - bottomOffset - 20);
        iframe.style.width = "420px";
        iframe.style.height = safeHeight + "px";
        iframe.style.bottom = bottomOffset + "px";
        iframe.style.right = "20px";
        iframe.style.left = "auto";
      }
    }
  };

  const updateSearchWrapperDimensions = () => {
    if (!searchWrapper) return;
    const isMobile = window.innerWidth <= 640;
    if (isMobile) {
      searchWrapper.style.left = "50%";
      searchWrapper.style.transform = "translateX(-50%)";
      searchWrapper.style.right = "auto";
      searchWrapper.style.width = "92%";
      searchWrapper.style.bottom = "20px";
    } else {
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
        searchWrapper.style.left = "auto";
        searchWrapper.style.transform = "none";
        searchWrapper.style.width = "90%";
        searchWrapper.style.maxWidth = "420px";
      }
    }
  };

  window.addEventListener("resize", () => {
    updateIframeDimensions();
    updateSearchWrapperDimensions();
  });

  // Set initial layouts
  updateIframeDimensions();

  document.body.appendChild(iframe);

  const openIframe = (initialQuery = "") => {
    // Hide search bar wrapper to prevent double input boxes
    if (chatType === "search" && searchWrapper) {
      searchWrapper.style.display = "none";
    }

    iframe.classList.add("show");

    // Send initial query via postMessage to avoid slow reloads
    if (initialQuery) {
      setTimeout(() => {
        iframe.contentWindow.postMessage({ type: "send-query", query: initialQuery }, "*");
      }, 50);
    }
  };

  const closeIframe = () => {
    iframe.classList.remove("show");

    // Show search bar wrapper back
    if (chatType === "search" && searchWrapper) {
      searchWrapper.style.display = "block";
      updateSearchWrapperDimensions();
    }
  };

  // Listen to postMessage from the iframe widget to close/collapse the chat window
  window.addEventListener("message", (event) => {
    if (event.data && (event.data.type === "close-chat" || event.data.type === "close")) {
      closeIframe();
    }
  });

  if (chatType === "search") {
    // --- Style 2: Search Bar Style Chat ---
    searchWrapper = document.createElement("div");
    searchWrapper.style.position = "fixed";
    searchWrapper.style.zIndex = "999998";
    searchWrapper.style.boxSizing = "border-box";
    searchWrapper.style.fontFamily = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";

    updateSearchWrapperDimensions();

    // Outer glow container (which handles brand gradient outline on focus/hover)
    const glowContainer = document.createElement("div");
    glowContainer.className = "grag-search-glow";

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
      glowContainer.classList.add("active");
    };
    input.onblur = () => {
      if (input.value.trim() === "") {
        glowContainer.classList.remove("active");
      }
    };
    input.oninput = (e) => {
      const val = e.target.value.trim();
      if (val.length > 0) {
        glowContainer.classList.add("active");
        sendBtn.style.background = themeColor;
        sendBtn.style.color = "#ffffff";
        sendBtn.disabled = false;
      } else {
        glowContainer.classList.remove("active");
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
      glowContainer.classList.remove("active");
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

    // Powered by Gramosoft label
    const poweredBy = document.createElement("a");
    poweredBy.href = "https://gramosoft.tech/";
    poweredBy.target = "_blank";
    poweredBy.rel = "noopener noreferrer";
    poweredBy.style.display = "block";
    poweredBy.style.textAlign = "center";
    poweredBy.style.marginTop = "6px";
    poweredBy.style.fontSize = "11px";
    poweredBy.style.color = "#a1a1aa";
    poweredBy.style.userSelect = "none";
    poweredBy.style.textDecoration = "none";
    poweredBy.style.cursor = "pointer";
    poweredBy.innerHTML = `Powered by <span style="font-weight: 600; color: #71717a;">Gramosoft</span>`;

    // Assemble and render elements
    inputBar.appendChild(leftIcon);
    inputBar.appendChild(input);
    inputBar.appendChild(sendBtn);
    glowContainer.appendChild(inputBar);
    searchWrapper.appendChild(glowContainer);
    searchWrapper.appendChild(poweredBy);
    document.body.appendChild(searchWrapper);
  } else {
    // --- Style 1: Classic Icon Style Chat ---
    const button = document.createElement("button");
    button.className = "grag-icon-btn";
    if (showButtonText && buttonText) {
      button.style.width = "auto";
      button.style.borderRadius = "30px";
      button.style.padding = "0 18px";
      button.style.gap = "8px";
    }

    let iconHtml = "";
    if (buttonIcon && (buttonIcon.startsWith("http") || buttonIcon.startsWith("blob:") || buttonIcon.startsWith("data:"))) {
      iconHtml = `<img src="${buttonIcon}" style="width: 28px; height: 28px; border-radius: 50%; object-fit: contain;" />`;
    } else if (buttonIcon === "robot") {
      iconHtml = `<div style="width: 28px; height: 28px; border-radius: 50%; background: ${themeColor}; display: flex; items-center: center; justify-content: center;"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="10" rx="2" fill="none"/><circle cx="8.5" cy="15.5" r="1.5" fill="white"/><circle cx="15.5" cy="15.5" r="1.5" fill="white"/><path d="M12 2v6M9 5h6"/></svg></div>`;
    } else if (buttonIcon === "setting") {
      iconHtml = `<div style="width: 28px; height: 28px; border-radius: 50%; background: ${themeColor}; display: flex; items-center: center; justify-content: center;"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg></div>`;
    } else if (buttonIcon === "question") {
      iconHtml = `<div style="width: 28px; height: 28px; border-radius: 50%; background: ${themeColor}; display: flex; items-center: center; justify-content: center;"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg></div>`;
    } else if (buttonIcon === "book") {
      iconHtml = `<div style="width: 28px; height: 28px; border-radius: 50%; background: ${themeColor}; display: flex; items-center: center; justify-content: center;"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg></div>`;
    } else {
      iconHtml = `
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M21 11.5C21 16.7467 16.9706 21 12 21C10.1302 21 8.39632 20.3992 6.97743 19.3722L3 20.5L4.15064 16.6329C3.41732 15.1543 3 13.4754 3 11.5C3 6.25329 7.02944 2 12 2C16.9706 2 21 6.25329 21 11.5Z" fill="${themeColor}" stroke="${themeColor}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          <circle cx="8" cy="11.5" r="1.3" fill="white"/>
          <circle cx="12" cy="11.5" r="1.3" fill="white"/>
          <circle cx="16" cy="11.5" r="1.3" fill="white"/>
        </svg>
      `;
    }

    button.innerHTML = iconHtml + (showButtonText && buttonText ? `<span style="font-weight: 700; font-size: 14px; color: ${themeColor}; font-family: sans-serif;">${buttonText}</span>` : "");

    document.body.appendChild(button);

    // Fetch Customization API if tenantId exists to apply logo_url to embed launch button if show_in_embed is true
    if (tenantId) {
      try {
        const custApiUrl = `${baseUrl.endsWith("/api/v1") ? baseUrl : baseUrl + "/api/v1"}/embed/customization?tenant_id=${tenantId}`;
        fetch(custApiUrl)
          .then(res => res.json())
          .then(result => {
            const data = result.data || result;
            if (data && data.logo_url && data.show_in_embed && button) {
              const imgHtml = `<img src="${data.logo_url}" style="width: 28px; height: 28px; border-radius: 50%; object-fit: contain;" />`;
              button.innerHTML = imgHtml + (showButtonText && buttonText ? `<span style="font-weight: 700; font-size: 14px; color: ${themeColor}; font-family: sans-serif;">${buttonText}</span>` : "");
            }
          })
          .catch(e => console.warn("GragWidget: Customization fetch error", e));
      } catch (e) { }
    }

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